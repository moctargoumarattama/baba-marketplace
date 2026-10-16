# Visuel de la catégorie Services

Le visuel de coiffure est remplacé dans la vignette Services et dans la bannière par une photographie illustrative de plusieurs métiers : entretien, réparation, bureau et informatique. À la demande de l'utilisateur, les trois professionnels sont désormais des personnes noires.

- Outil : imagegen intégré, génération initiale puis modification du visuel.
- Fichier intégré : `dealnova/app/static/images/home-refresh/services-multimetiers-v2.webp`.
- Première version conservée : `dealnova/app/static/images/home-refresh/services-multimetiers.webp`.
- Dimensions : 1470 × 1070 px ; conversion WebP sans recadrage ni modification de l'image générée.

## Vérification

- 13 tests de la page d'accueil réussis après intégration de la deuxième version.
- Deuxième version : fichier WebP valide, dimensions conservées et références de la vignette et de la bannière vérifiées ; version du CSS actualisée pour le cache.
- Première version : Chromium et WebKit, défilement, pause, gestes tactiles, liens et affichage à 320, 390 et 1280 px vérifiés.
- Aperçu mobile de la première version : `services-multimetiers-mobile.png`.
- Aperçu exécuté sur une copie temporaire de la base de données.

## Prompt final de modification

Use case: precise-object-edit. Asset type: BabaMarket Services category photograph and homepage banner. Input image 1 is the edit target. Primary request: replace all three pictured professionals with Black adults with naturally dark brown skin: a Black woman on the left, a Black man in the middle, and a Black woman on the right. Give each person natural, distinct facial features and realistic skin texture, with the same friendly professional expressions. Preserve the three professions, poses, body placement, clothing and colors, cleaning caddy and cloth, wrench and tool case, laptop and notebook, room, warm ivory/emerald palette, lighting, camera angle, landscape dimensions and overall composition. Keep each person and their identifying tools clearly readable in a small services thumbnail. Change only the people as requested; keep the rest of the image as close to the original as possible. Photorealistic, realistic anatomy, no text, no logos, no watermark. Deliver only the edited photograph.

## Prompt de génération initiale

Use case: photorealistic-natural. Asset type: photograph for the broad Services category of BabaMarket, a local marketplace in Morocco; also reused in its services homepage banner. Primary request: communicate MANY TYPES of professional services at a glance, not only hairdressing. Create one polished, realistic editorial composite with three equally prominent professionals and recognizable activities, softly blended into a coherent warm ivory setting: on the left a Moroccan woman in neutral workwear providing home maintenance/cleaning, carrying a small unbranded cleaning caddy and folded cloth; in the middle a Moroccan repair artisan in forest-green workwear holding a compact tool case and a wrench; on the right a Moroccan office/IT professional in smart casual clothes using an open laptop with a notebook. Balanced equal emphasis, clear distinct large silhouettes and tools, waist-up or chest-up, three people only, clean composition readable as a small 110x80 category thumbnail. Composition: landscape 4:3, keep the three people and their identifying objects within the central 80%, comfortable margin around heads, uncluttered background, no thick dividers or tiny inset panels. Natural window light, warm beige and ivory with restrained emerald accents matching an ivory/green marketplace UI, realistic anatomy, natural candid expressions. Text: none. No words, logos, watermarks, salon equipment, uniforms with labels, fake UI, extra fingers, floating icons, or oversized foreground tools. This is an illustrative category photograph, not a UI screenshot. Deliver just the image.
