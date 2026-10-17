import importlib.util
from contextlib import nullcontext
from getpass import GetPassWarning
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import warnings

import pytest
from sqlalchemy import column


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/create_admin.py"
PASSWORD = "TestOnlyAdministrator42!"
ARGS = ["--username", " NewAdmin ", "--email", " ADMIN@example.test "]


@pytest.fixture()
def cli(monkeypatch):
    spec = importlib.util.spec_from_file_location("isolated_create_admin_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_load_runtime", Mock(side_effect=AssertionError("Unexpected application loading")))
    monkeypatch.setattr(module, "getpass", Mock(side_effect=[PASSWORD, PASSWORD]))
    return module


def _mock_runtime(cli, existing=None):
    app = SimpleNamespace(app_context=lambda: nullcontext())
    factory = Mock(return_value=app)
    db = SimpleNamespace(session=Mock())
    user_model = Mock()
    user_model.username = column("username")
    user_model.email = column("email")
    user_model.query.filter.return_value.first.return_value = existing
    cli._load_runtime.side_effect = None
    cli._load_runtime.return_value = (factory, db, user_model)
    return factory, db, user_model


def test_help_does_not_prompt_or_initialize_application(cli):
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])

    assert result.value.code == 0
    cli.getpass.assert_not_called()
    cli._load_runtime.assert_not_called()


@pytest.mark.parametrize("arguments", [
    [],
    ["--username", "", "--email", "admin@example.test"],
    ["--username", "two names", "--email", "admin@example.test"],
    ["--username", "a" * 81, "--email", "admin@example.test"],
    ["--username", "admin", "--email", "invalid-address"],
    ["--username", "admin", "--email", "a" * 110 + "@example.test"],
])
def test_invalid_identity_is_rejected_before_prompt_or_application_loading(cli, arguments):
    with pytest.raises(SystemExit) as result:
        cli.main(arguments)

    assert result.value.code == 2
    cli.getpass.assert_not_called()
    cli._load_runtime.assert_not_called()


@pytest.mark.parametrize("password, confirmation", [
    ("short", "short"),
    (" " * 14, " " * 14),
    (PASSWORD, PASSWORD + "different"),
])
def test_invalid_password_is_rejected_before_application_loading(cli, capsys, password, confirmation):
    cli.getpass.side_effect = [password, confirmation]

    assert cli.main(ARGS) == 2

    cli._load_runtime.assert_not_called()
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_cancelled_password_input_never_loads_application(cli, interruption):
    cli.getpass.side_effect = interruption

    assert cli.main(ARGS) == 2

    cli._load_runtime.assert_not_called()


def test_password_input_refuses_getpass_echo_fallback(cli, monkeypatch):
    def insecure_prompt(_prompt):
        warnings.warn("Hidden input unavailable", GetPassWarning)
        pytest.fail("Password input must stop before echoed fallback")

    monkeypatch.setattr(cli, "getpass", insecure_prompt)

    assert cli.main(ARGS) == 2

    cli._load_runtime.assert_not_called()


def test_new_admin_uses_supplied_identity_and_password_without_displaying_it(cli, capsys):
    factory, db, user_model = _mock_runtime(cli)

    assert cli.main(ARGS) == 0

    factory.assert_called_once_with()
    user_model.assert_called_once_with(username="NewAdmin", email="admin@example.test", role="admin")
    user_model.return_value.set_password.assert_called_once_with(PASSWORD)
    db.session.add.assert_called_once_with(user_model.return_value)
    db.session.commit.assert_called_once_with()
    db.session.rollback.assert_not_called()
    condition = user_model.query.filter.call_args.args[0]
    assert set(condition.compile().params.values()) == {"newadmin", "admin@example.test"}
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err


def test_existing_account_is_never_modified(cli, capsys):
    existing = Mock()
    _factory, db, user_model = _mock_runtime(cli, existing=existing)

    assert cli.main(ARGS) == 1

    user_model.assert_not_called()
    existing.set_password.assert_not_called()
    assert not db.session.mock_calls
    output = capsys.readouterr()
    assert "refusee" in output.err
    assert PASSWORD not in output.out + output.err


def test_failed_write_rolls_back_and_does_not_expose_exception_credentials(cli, capsys):
    _factory, db, _user_model = _mock_runtime(cli)
    db.session.commit.side_effect = RuntimeError(PASSWORD)

    assert cli.main(ARGS) == 1

    db.session.rollback.assert_called_once_with()
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err
