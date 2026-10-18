"""Owner archive rendering and filters against a disposable database."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import template_rendered
import pytest

from dealnova.tests.test_owner_location_modal import isolated_owner_application


@pytest.fixture(scope="module")
def archives_application(tmp_path_factory):
    with isolated_owner_application(tmp_path_factory.mktemp("owner-archives")) as fixture:
        from dealnova.app.models.rental import RentalArchive
        from dealnova.app.models.shop import Shop

        with fixture.app.app_context():
            second_shop = Shop(name="Deuxième agence", slug="archives-second", vendor_id=fixture.ids.vendor,
                               is_active=True, primary_type="location", allowed_types_json='["location"]')
            fixture.db.session.add(second_shop)
            fixture.db.session.flush()
            fixture.ids.second_shop = second_shop.id

            def add_archive(title, **changes):
                values = dict(owner_id=fixture.ids.vendor, shop_id=fixture.ids.shop, title=title,
                              city="Rabat", area="Centre", listing_type="monthly", property_type="apartment",
                              rent_cents=250000, deposit_cents=100000, owner_fee_cents=40000,
                              platform_commission_rate_bps=1250, platform_commission_fixed_cents=1000,
                              platform_commission_amount_cents=6000, archived_view_count=25,
                              closed_reason="taken", closed_at=datetime.utcnow() - timedelta(hours=1),
                              created_at_original=datetime.utcnow() - timedelta(days=3),
                              expires_at_original=datetime.utcnow() + timedelta(days=10))
                values.update(changes)
                item = RentalArchive(**values)
                fixture.db.session.add(item)
                fixture.db.session.flush()
                return item.id

            fixture.target = SimpleNamespace()
            for index in range(25):
                add_archive(f"Appartement ordinaire {index:02d}",
                            closed_reason=("taken", "expired", "deleted_by_owner", "deleted_by_admin")[index % 4],
                            closed_at=datetime.utcnow() - timedelta(minutes=index + 1))
            fixture.target.older_page = add_archive("Studio lumineux", city="Salé", area="Hay Salam",
                closed_at=datetime.utcnow() - timedelta(days=2))
            fixture.target.second = add_archive("Chambre côté jardin", shop_id=second_shop.id, listing_type="daily",
                property_type="room", owner_fee_cents=None, deposit_cents=None, closed_reason="expired")
            fixture.target.escaped = add_archive('<img src=x onerror="alert(1)">', owner_fee_text="Frais <test>")
            fixture.target.foreign = add_archive("SECRET AUTRE VENDEUR", owner_id=fixture.ids.foreign_owner,
                                                  shop_id=fixture.ids.foreign_shop)
            fixture.target.old = add_archive("SECRET HORS PÉRIODE", closed_at=datetime.utcnow() - timedelta(days=8))
            fixture.db.session.commit()
        yield fixture


@pytest.fixture()
def archives(archives_application):
    fixture = archives_application
    client = fixture.app.test_client()
    with client.session_transaction() as storage:
        storage["_user_id"] = str(fixture.ids.vendor)
        storage["_fresh"] = True
    return SimpleNamespace(**vars(fixture), client=client)


def _get(fixture, **query):
    contexts = []
    def rendered(sender, template, context, **extra):
        if template.name == "locations/owner_archives.html":
            contexts.append(context)
    with template_rendered.connected_to(rendered, fixture.app):
        response = fixture.client.get("/owner/locations/archives", query_string=query)
    assert response.status_code == 200
    return response, contexts[-1]


def test_owned_archives_remain_paginated_and_keep_existing_history_period(archives):
    response, context = _get(archives)
    assert context["pagination"].total == 28
    assert len(context["archives"]) == 20
    assert context["history_days"] == 7
    assert archives.target.older_page not in {item.id for item in context["archives"]}
    html = response.get_data(as_text=True)
    assert "SECRET AUTRE VENDEUR" not in html and "SECRET HORS PÉRIODE" not in html
    assert 'class="bm-vendor-dashboard bm-vendor-records bm-owner-archives"' in html
    assert 'id="archiveDetailDialog"' in html


@pytest.mark.parametrize("query,key", [("Studio", "older_page"), ("Hay Salam", "older_page"), ("Salé", "older_page"), ("Chambre", "second")])
def test_search_reaches_all_owned_archives_and_city_area(archives, query, key):
    _, context = _get(archives, q=query)
    assert [item.id for item in context["archives"]] == [getattr(archives.target, key)]


@pytest.mark.parametrize("status", ["taken", "expired", "deleted_by_owner", "deleted_by_admin"])
def test_reason_filter_keeps_only_selected_reason(archives, status):
    _, context = _get(archives, status=status)
    assert context["archives"]
    assert {item.closed_reason for item in context["archives"]} == {status}


def test_shop_filter_cannot_reveal_another_owner_and_invalid_values_clear(archives):
    _, context = _get(archives, shop=archives.ids.foreign_shop, status="unexpected")
    assert context["selected_shop_id"] is None and context["status"] == ""
    assert context["pagination"].total == 28
    _, context = _get(archives, shop=archives.ids.second_shop)
    assert [item.id for item in context["archives"]] == [archives.target.second]


def test_last_page_is_clamped_and_filter_context_is_retained_in_links(archives):
    response, context = _get(archives, page=999, q="Appartement")
    assert context["pagination"].page == 2
    assert context["pagination"].total == 25
    assert len(context["archives"]) == 5
    assert "q=Appartement" in response.get_data(as_text=True)


def test_detail_content_is_single_escaped_source_with_existing_money_values(archives):
    response, _ = _get(archives, q="onerror")
    html = response.get_data(as_text=True)
    assert html.count("data-archive-detail-content") == 1
    assert html.count("data-archive-row") == 1
    assert '&lt;img src=x onerror=&#34;alert(1)&#34;&gt;' in html
    assert '<img src=x onerror="alert(1)">' not in html
    assert "Frais &lt;test&gt;" in html
    assert "60 DH" in html
    assert "12.5 %" in html
    assert "Consultations" in html


def test_live_get_retains_same_server_filters_and_page_contract(archives):
    response = archives.client.get("/owner/locations/archives?q=Studio",
                                   headers={"X-Requested-With": "XMLHttpRequest", "Accept": "text/html"})
    assert response.status_code == 200 and not response.is_json
    html = response.get_data(as_text=True)
    assert 'data-archive-total="1"' in html and 'data-archive-page="1"' in html
    assert "Studio lumineux" in html and "Appartement ordinaire" not in html


def test_location_only_workspace_has_no_catalog_or_cashbook_links(archives):
    from dealnova.app.models.shop import Shop
    with archives.app.app_context():
        shop = archives.db.session.get(Shop, archives.ids.shop)
        initial = shop.allowed_types_json
        initial_primary = shop.primary_type
        shop.primary_type = "location"
        shop.allowed_types_json = '["location"]'
        archives.db.session.commit()
    try:
        _, context = _get(archives)
        assert not context["allows_catalog"] and not context["allows_products"]
        assert context["allows_location"]
    finally:
        with archives.app.app_context():
            shop = archives.db.session.get(Shop, archives.ids.shop)
            shop.allowed_types_json = initial
            shop.primary_type = initial_primary
            archives.db.session.commit()


def test_anonymous_requests_still_require_login(archives):
    response = archives.app.test_client().get("/owner/locations/archives")
    assert response.status_code in (302, 303) and "/login" in response.location
