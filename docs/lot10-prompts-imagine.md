# Lot 10 — fiches et prompts Imagine

Graine `iswing-10`. Date de référence `2026-10-04`. Ville `Lyon|FR|45.74906|4.84789`. Lot `lot10`. Dix comptes, trois photos chacun.

Ce fichier est le verrou. Si un champ du générateur se contredit (cheveux rasés et bouclés, par exemple), la description ci-dessous tranche. Les trois photos d'un compte montrent les mêmes personnes. Seuls le lieu, la pose et les vêtements changent.

## Comment générer

1. Générer d'abord la photo `0`.
2. Pour les photos `1` et `2`, joindre la photo `0` comme image de référence dans Imagine, puis coller le prompt.
3. Enregistrer les fichiers exactement ainsi :
   - `lot10-lyonfr-XXXX/0.jpg` — principale, publique
   - `lot10-lyonfr-XXXX/1.jpg` — secondaire, publique
   - `lot10-lyonfr-XXXX/2.jpg` — privée
4. Visage : le mode s'applique aux trois photos et à toutes les personnes du compte.
   - `visible` : visage net, sans flou, sans sticker, sans lunettes de soleil.
   - `blurred` : le flou est dans l'image, du front au menton, d'oreille à oreille. Le corps et le décor restent nets.
   - `emoji` : un smiley jaune opaque couvre chaque visage. Aucun œil, nez ou bouche humaine visible.

Toutes les photos : adultes fictifs, habillés, sans nudité, sans acte sexuel, sans logo, sans texte lisible, sans troisième personne.

---

## 01 — lot10-lyonfr-0001 — Nina & Nora

- Type : couple FF. Visage : **visible** sur les deux.
- Nina, femme, 40 ans, née le 1985-11-06. Nora, femme, 37 ans, née le 1988-11-18.
- Nina à gauche, Nora à droite, dans les trois photos.

Verrou Nina : femme adulte de 40 ans, peau brune uniforme, visage ovale, pommettes hautes, nez droit et fin, lèvres moyennes fermées. Yeux noisette en amande, cils courts, sourcils noirs arqués et nets. Cheveux rasés à 3 mm, boucles serrées brun-noir visibles sur le cuir chevelu, pas chauve, pas de cheveux longs. Silhouette mince, 1,68 m, épaules étroites. Pas de barbe, pas de lunettes, pas de tache. Petit clou doré à l'oreille gauche seulement.

Verrou Nora : femme adulte de 37 ans, peau claire avec des taches de rousseur sur le nez et les joues, mâchoire carrée, nez légèrement retroussé, lèvres fines. Yeux bleus ronds, sourcils roux fournis. Cheveux roux cuivré, bouclés serrés, longueur d'épaules, raie au milieu, jamais attachés. Silhouette athlétique, 1,74 m, épaules droites. Pas de barbe, pas de lunettes.

### Prompt 0 — `lot10-lyonfr-0001/0.jpg`

```text
Original fictional photograph, realistic, 35mm, natural skin texture, not an illustration. Exactly two adult women, no third person, no reflection of another face. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe terrace, daytime, waist-up, both looking at the camera. Nina on the left, Nora on the right.

Nina, left: 40-year-old woman, even brown skin, oval face, high cheekbones, narrow straight nose, medium closed lips, almond hazel eyes, short lashes, neat arched black eyebrows. Hair buzzed to 3 mm with tight brown-black coils visible on the scalp, not bald, not long. Slim build, narrow shoulders. No beard, no glasses, no birthmark. One small gold stud in the left ear only.

Nora, right: 37-year-old woman, fair skin with freckles across the nose and cheeks, square jaw, slightly upturned nose, thin lips, round blue eyes, thick copper eyebrows. Shoulder-length tight copper-red curls, center part, never tied. Athletic build, straight shoulders. No beard, no glasses.

Clothes: Nina in a black turtleneck, Nora in an olive shirt jacket. FACE MODE VISIBLE: both faces sharp, fully visible, no blur, no sticker, no sunglasses, no mask.
```

### Prompt 1 — `lot10-lyonfr-0001/1.jpg`

Joindre la photo 0 en référence.

```text
Same two women as the reference photo. IDENTITY LOCK: do not change age, skin, face shape, eyes, nose, mouth, haircut, curls, freckles, build or the single gold stud. Only clothes, pose and background change. Nina stays on the left, Nora on the right. Exactly two adults.

Three-quarter length, walking on the Saône quay in Lyon, daytime, plane trees. Nina wears a navy coat, Nora a cream knit sweater. Both faces toward the camera. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text, no extra person.

FACE MODE VISIBLE: both faces sharp and fully visible, no blur, no sticker, no sunglasses.
```

### Prompt 2 — `lot10-lyonfr-0001/2.jpg`

Joindre la photo 0 en référence.

```text
Same two women as the reference photo. IDENTITY LOCK: same faces, same buzzed coiled hair on Nina, same shoulder-length copper curls and freckles on Nora. Nina left, Nora right. Exactly two adults.

Seated at a Lyon restaurant table at dusk, waist-up. Nina wears a charcoal blazer, Nora a dark green V-neck sweater. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text, no extra person.

FACE MODE VISIBLE: both faces sharp and fully visible, no blur, no sticker, no sunglasses.
```

---

## 02 — lot10-lyonfr-0002 — Angel

- Type : célibataire, personne non binaire, 53 ans, née le 1972-11-03. Visage : **visible**.
- L'identité non binaire ne dicte pas le corps. Seul le verrou ci-dessous compte.

Verrou : adulte de 53 ans, peau foncée, visage long, front haut, nez large et droit, lèvres pleines, yeux gris écartés, sourcils bruns droits. Cheveux bruns bouclés, volume moyen, longueur au menton, raie libre, quelques fils gris aux tempes. Pas de barbe, pas de maquillage, pas de lunettes. Silhouette moyenne, 1,72 m, épaules moyennes, avant-bras sans pilosité visible.

### Prompt 0 — `lot10-lyonfr-0002/0.jpg`

```text
Original fictional photograph, realistic, one single adult, no other person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up, looking at the camera.

The adult is 53, dark skin, long face, high forehead, wide straight nose, full lips, widely set grey eyes, straight brown eyebrows. Chin-length curly brown hair with a few grey strands at the temples, medium volume. No beard, no makeup, no glasses. Medium build. Plain sand-colored overshirt.

FACE MODE VISIBLE: face sharp and fully visible, no blur, no sticker, no sunglasses.
```

### Prompt 1 — `lot10-lyonfr-0002/1.jpg`

Joindre la photo 0 en référence.

```text
Same adult as the reference. IDENTITY LOCK: same age, dark skin, long face, grey eyes, wide nose, full lips, chin-length curly brown hair with grey at the temples, no beard, medium build. Only clothes and place change. Exactly one person.

Walking on the Saône quay in Lyon, daytime, three-quarter length, navy chore coat. Fully clothed, non-explicit, no nudity, no logo, no readable text.

FACE MODE VISIBLE: face sharp and fully visible, no blur, no sticker, no sunglasses.
```

### Prompt 2 — `lot10-lyonfr-0002/2.jpg`

Joindre la photo 0 en référence.

```text
Same adult as the reference. IDENTITY LOCK unchanged: 53, dark skin, long face, grey eyes, chin-length curly brown hair with grey temples, no beard. Exactly one person.

Seated at a Lyon restaurant at dusk, grey linen shirt. Fully clothed, non-explicit, no nudity, no logo, no readable text.

FACE MODE VISIBLE: face sharp and fully visible, no blur, no sticker, no sunglasses.
```

---

## 03 — lot10-lyonfr-0003 — Amina

- Célibataire, femme, 37 ans, née le 1989-02-17. Visage : **visible**.

Verrou : femme de 37 ans, peau clair doré, visage rond, joues pleines, nez court, lèvres moyennes, yeux noisette légèrement tombants, sourcils noirs épais. Cheveux rasés à 3 mm, texture bouclée noire visible sur le cuir chevelu, pas chauve, pas de longueur. Silhouette solide, 1,70 m, épaules larges, cou large. Pas de barbe, pas de lunettes, pas de taches de rousseur.

### Prompt 0 — `lot10-lyonfr-0003/0.jpg`

```text
Original fictional photograph, realistic, exactly one adult woman, no other person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up, looking at the camera.

37-year-old woman, golden-fair skin, round face, full cheeks, short nose, medium lips, slightly downturned hazel eyes, thick black eyebrows. Hair buzzed to 3 mm with visible black coil texture on the scalp, not bald and not long. Solid build, broad shoulders, wide neck. No beard, no glasses, no freckles. Ivory button shirt.

FACE MODE VISIBLE: face sharp and fully visible, no blur, no sticker, no sunglasses.
```

### Prompt 1 — `lot10-lyonfr-0003/1.jpg`

Joindre la photo 0 en référence.

```text
Same woman as the reference. IDENTITY LOCK: 37, golden-fair skin, round face, short nose, downturned hazel eyes, thick black brows, 3 mm black coiled buzz cut, solid broad-shouldered build. Exactly one person. Saône quay, Lyon, daytime, three-quarter length, black coat.

Fully clothed, non-explicit, no nudity, no logo, no readable text. FACE MODE VISIBLE: face sharp, no blur, no sticker, no sunglasses.
```

### Prompt 2 — `lot10-lyonfr-0003/2.jpg`

Joindre la photo 0 en référence.

```text
Same woman as the reference. IDENTITY LOCK unchanged, including the 3 mm coiled buzz cut and round face. Exactly one person. Lyon restaurant at dusk, seated, rust-colored knit sweater.

Fully clothed, non-explicit, no nudity, no logo, no readable text. FACE MODE VISIBLE: face sharp, no blur, no sticker, no sunglasses.
```

---

## 04 — lot10-lyonfr-0004 — Inès

- Célibataire, femme, 49 ans, née le 1977-01-15. Visage : **blurred** sur les trois photos.
- Le corps et les cheveux restent reconnaissables. Le visage est illisible dans le fichier.

Verrou : femme de 49 ans, peau clair doré, visage ovale allongé, cheveux blonds raides mi-longs jusqu'aux clavicules, raie sur le côté gauche, pas de boucles. Yeux noisette (ils seront floutés). Silhouette mince, 1,66 m. Pas de barbe, pas de lunettes, pas de tache, pas de bijou.

### Prompt 0 — `lot10-lyonfr-0004/0.jpg`

```text
Original fictional photograph, realistic, exactly one adult woman, no other person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up.

49-year-old woman, golden-fair skin, long oval face, straight blonde hair to the collarbones, left side part, no curls. Slim build. No beard, no glasses, no jewelry, no birthmark. Light blue shirt.

FACE MODE BLURRED: keep hair, neck, clothes and background sharp, but the face from forehead to chin and ear to ear is heavily gaussian-blurred inside the image so eyes, nose and mouth cannot be recognized. Do not crop the head off. Do not use a sticker.
```

### Prompt 1 — `lot10-lyonfr-0004/1.jpg`

Joindre la photo 0 en référence.

```text
Same woman as the reference. IDENTITY LOCK: 49, golden-fair skin, straight blonde collarbone-length hair with a left part, slim build, no glasses, no beard. Exactly one person. Saône quay, Lyon, daytime, grey coat.

FACE MODE BLURRED: the face itself is heavily blurred in the file, unreadable, while hair and body stay sharp. No sticker, no cropped head. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

### Prompt 2 — `lot10-lyonfr-0004/2.jpg`

Joindre la photo 0 en référence.

```text
Same woman as the reference. IDENTITY LOCK unchanged: straight blonde hair to the collarbones, slim, 49. Exactly one person. Lyon restaurant at dusk, black blouse.

FACE MODE BLURRED: face heavily blurred inside the image, hair and clothes sharp, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

---

## 05 — lot10-lyonfr-0005 — Mateo & Paul

- Couple HH. Visage : **visible** sur les deux.
- Mateo, homme, 58 ans, né le 1968-07-24, à gauche. Paul, homme, 49 ans, né le 1976-10-30, à droite.

Verrou Mateo : homme de 58 ans, peau mate, visage étroit, nez aquilin, yeux verts en amande, sourcils gris. Cheveux poivre et sel coupés court, légèrement ondulés, pas longs. Barbe de trois jours poivre et sel, pas une barbe pleine. Silhouette mince, 1,78 m. Petite tache de naissance brune ronde, 1 cm, sur le côté gauche du cou, toujours visible. Pas de lunettes.

Verrou Paul : homme de 49 ans, peau mate, visage carré, nez droit, yeux bleus, sourcils noirs. Cheveux noirs longs, lisses, jusqu'aux épaules, souvent derrière les oreilles mais la même longueur. Pas de barbe, mâchoire glabre. Silhouette athlétique, 1,82 m, épaules larges. Pas de lunettes, pas de tache.

### Prompt 0 — `lot10-lyonfr-0005/0.jpg`

```text
Original fictional photograph, realistic, exactly two adult men, no third person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up, both looking at the camera. Mateo on the left, Paul on the right.

Mateo, left: 58-year-old man, matte medium-brown skin, narrow face, aquiline nose, almond green eyes, grey eyebrows. Short wavy salt-and-pepper hair, not long. Light salt-and-pepper stubble, not a full beard. Slim build. A round 1 cm brown birthmark on the left side of the neck. No glasses.

Paul, right: 49-year-old man, matte medium-brown skin, square face, straight nose, blue eyes, black eyebrows. Straight black hair to the shoulders, worn behind the ears, same length. Clean-shaven. Athletic, broad shoulders. No glasses, no birthmark.

Clothes: Mateo in a navy sweater, Paul in a white oxford shirt. FACE MODE VISIBLE: both faces sharp, no blur, no sticker, no sunglasses.
```

### Prompt 1 — `lot10-lyonfr-0005/1.jpg`

Joindre la photo 0 en référence.

```text
Same two men as the reference. IDENTITY LOCK: Mateo left, 58, short salt-and-pepper hair, green eyes, neck birthmark, stubble, slim. Paul right, 49, straight black hair to the shoulders, blue eyes, clean-shaven, athletic. Do not swap them. Exactly two adults.

Saône quay, Lyon, daytime. Mateo in a camel coat, Paul in a black jacket. FACE MODE VISIBLE: both faces sharp, no blur, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

### Prompt 2 — `lot10-lyonfr-0005/2.jpg`

Joindre la photo 0 en référence.

```text
Same two men as the reference. IDENTITY LOCK unchanged, birthmark still on Mateo's left neck, Paul's hair still shoulder-length and black. Mateo left, Paul right. Exactly two adults.

Lyon restaurant at dusk. Mateo in a grey shirt, Paul in a dark green sweater. FACE MODE VISIBLE: both faces sharp, no blur, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

---

## 06 — lot10-lyonfr-0006 — Yan & Amina

- Couple HF. Visage : **emoji** sur les deux, dans les trois photos.
- Yan, homme, 52 ans, né le 1974-01-30, à gauche. Amina, femme, 27 ans, née le 1999-02-12, à droite.
- Les cheveux, lunettes et silhouettes restent visibles autour du sticker.

Verrou Yan : homme de 52 ans, peau clair doré, visage rond, cheveux blonds courts et raides, légèrement dégarnis aux tempes. Lunettes rectangulaires à fine monture noire, toujours présentes (par-dessus ou autour du sticker, les verres ne montrent pas les yeux). Yeux noisette, invisibles sous l'emoji. Silhouette moyenne, 1,76 m. Barbe absente.

Verrou Amina : femme de 27 ans, peau brune, cheveux noirs longs et raides jusqu'au milieu du dos, raie au milieu. Fossettes (cachées par l'emoji, ne pas les dessiner sur la peau visible). Silhouette solide, 1,73 m. Pas de lunettes, pas de barbe.

### Prompt 0 — `lot10-lyonfr-0006/0.jpg`

```text
Original fictional photograph, realistic, exactly two adults, man on the left and woman on the right, no third person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up.

Yan, left: 52-year-old man, golden-fair skin, round face, short straight blond hair, thinning at the temples, medium build. Thin black rectangular glasses remain visible. No beard.

Amina, right: 27-year-old woman, brown skin, straight black hair to mid-back, center part, solid build. No glasses, no beard.

FACE MODE EMOJI: a large opaque yellow circle smiley covers each face completely from forehead to chin, ear to ear. Two black dot eyes and one simple curved smile are drawn on the sticker. No human eyes, nose, mouth or teeth visible. Hair and glasses stay outside the sticker. Apply to both people.

Clothes: Yan in a light blue shirt, Amina in a white T-shirt under an open denim jacket.
```

### Prompt 1 — `lot10-lyonfr-0006/1.jpg`

Joindre la photo 0 en référence.

```text
Same pair as the reference. IDENTITY LOCK: Yan left, 52, short blond hair thinning at the temples, black rectangular glasses, medium build. Amina right, 27, brown skin, straight black hair to mid-back, solid build. Exactly two adults.

Saône quay, Lyon. Yan in a grey wool coat, Amina in a long black coat. FACE MODE EMOJI: opaque yellow smiley covering each entire face, no human facial features visible. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

### Prompt 2 — `lot10-lyonfr-0006/2.jpg`

Joindre la photo 0 en référence.

```text
Same pair as the reference. IDENTITY LOCK unchanged. Yan left, Amina right. Exactly two adults. Lyon restaurant at dusk. Yan in a navy polo, Amina in a burgundy sweater.

FACE MODE EMOJI: each face fully covered by the same opaque yellow smiley, no human eyes or mouth. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

---

## 07 — lot10-lyonfr-0007 — Maya

- Célibataire, femme, 59 ans, née le 1967-06-02. Visage : **blurred**.
- Signe distinctif à garder : barbe courte. Elle reste lisible sous le flou du visage seulement si le flou couvre les yeux et le nez ; la barbe, les cheveux et le corps restent nets. Pour que le fichier soit bien flouté, le flou couvre aussi la barbe. Les cheveux châtains et la silhouette suffisent à la reconnaître. Ne pas retirer la barbe : elle est sous le flou, pas absente.

Verrou : femme de 59 ans, peau olive, visage ovale, cheveux châtains ondulés jusqu'aux épaules, raie au milieu, quelques cheveux gris. Yeux verts. Barbe et moustache courtes, poivre et sel, taillées nettes, pas une barbe longue. Silhouette moyenne, 1,65 m. Pas de lunettes.

### Prompt 0 — `lot10-lyonfr-0007/0.jpg`

```text
Original fictional photograph, realistic, exactly one adult woman, no other person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up.

59-year-old woman, olive skin, oval face, wavy chestnut hair to the shoulders, center part, a few grey strands. Medium build. She has a short trimmed salt-and-pepper beard and moustache. No glasses. Brown knit sweater.

FACE MODE BLURRED: the whole face including the beard area, from forehead to below the chin and ear to ear, is heavily gaussian-blurred in the image so eyes, nose, mouth and beard cannot be read. Hair outside that oval, neck, clothes and background stay sharp. Do not remove the beard by making her clean-shaven; it is hidden by blur. No sticker, do not crop the head off.
```

### Prompt 1 — `lot10-lyonfr-0007/1.jpg`

Joindre la photo 0 en référence.

```text
Same woman as the reference. IDENTITY LOCK: 59, olive skin, wavy chestnut shoulder-length hair, center part, medium build, short beard present but not readable. Exactly one person. Saône quay, Lyon, black coat.

FACE MODE BLURRED: face and beard area heavily blurred inside the file, hair sharp, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

### Prompt 2 — `lot10-lyonfr-0007/2.jpg`

Joindre la photo 0 en référence.

```text
Same woman as the reference. IDENTITY LOCK unchanged. Exactly one person. Lyon restaurant at dusk, cream blouse.

FACE MODE BLURRED: face heavily blurred in the file, chestnut hair sharp, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

---

## 08 — lot10-lyonfr-0008 — Lucas

- Célibataire, homme, 32 ans, né le 1994-06-27. Visage : **visible**.

Verrou : homme de 32 ans, peau claire, visage rectangulaire, mâchoire large, nez droit, yeux verts écartés, sourcils blonds. Cheveux blonds courts, raides, décoiffés vers l'avant, pas de calvitie. Rasé de près, aucune barbe. Silhouette solide, 1,86 m, cou épais, épaules larges. Pas de lunettes, pas de tache, pas de bijou. Avant-bras peu poilus.

### Prompt 0 — `lot10-lyonfr-0008/0.jpg`

```text
Original fictional photograph, realistic, exactly one adult man, no other person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up, looking at the camera.

32-year-old man, fair skin, rectangular face, broad jaw, straight nose, widely set green eyes, blond eyebrows. Short straight blond hair brushed forward, no balding. Clean-shaven. Solid tall build, thick neck, broad shoulders. No glasses, no birthmark, no jewelry. Heather grey sweater.

FACE MODE VISIBLE: face sharp and fully visible, no blur, no sticker, no sunglasses.
```

### Prompt 1 — `lot10-lyonfr-0008/1.jpg`

Joindre la photo 0 en référence.

```text
Same man as the reference. IDENTITY LOCK: 32, fair skin, rectangular face, green eyes, short blond hair forward, clean-shaven, solid broad build. Exactly one person. Saône quay, Lyon, navy overshirt.

FACE MODE VISIBLE: face sharp, no blur, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

### Prompt 2 — `lot10-lyonfr-0008/2.jpg`

Joindre la photo 0 en référence.

```text
Same man as the reference. IDENTITY LOCK unchanged. Exactly one person. Lyon restaurant at dusk, light blue button shirt.

FACE MODE VISIBLE: face sharp, no blur, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

---

## 09 — lot10-lyonfr-0009 — Paul & Nora

- Couple HF. Visage : **emoji** sur les deux.
- Paul, homme, 29 ans, né le 1997-04-15, à gauche. Nora, femme, 60 ans, née le 1966-08-02, à droite.
- Paul a déjà les cheveux poivre et sel à 29 ans : c'est voulu.

Verrou Paul : homme de 29 ans, peau claire, visage ovale, cheveux courts poivre et sel (majoritairement gris aux tempes, châtain au sommet), yeux gris, barbe courte taillée poivre et sel. Silhouette moyenne, 1,77 m. Pas de lunettes. La barbe dépasse un peu sous le sticker : un liseré de barbe reste visible sous le smiley, les yeux non.

Verrou Nora : femme de 60 ans, peau claire, cheveux noirs courts et lisses, coupe au-dessus des oreilles, quelques fils gris, yeux bleus invisibles sous l'emoji. Silhouette athlétique, 1,70 m. Pas de barbe, pas de lunettes.

### Prompt 0 — `lot10-lyonfr-0009/0.jpg`

```text
Original fictional photograph, realistic, exactly two adults, man on the left and woman on the right, no third person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up.

Paul, left: 29-year-old man, fair skin, oval face, short salt-and-pepper hair (grey at the temples, brown on top), medium build. A short trimmed salt-and-pepper beard. No glasses.

Nora, right: 60-year-old woman, fair skin, short straight black hair cut above the ears with a few grey strands, athletic build. No beard, no glasses.

FACE MODE EMOJI: a large opaque yellow smiley covers each face from forehead to chin. Two black dots and a simple curve on the sticker. No human eyes or mouth visible. A thin edge of Paul's beard may show under the sticker. Nora's short black hair stays visible around it. Apply to both.

Clothes: Paul in a black sweater, Nora in a steel-blue shirt.
```

### Prompt 1 — `lot10-lyonfr-0009/1.jpg`

Joindre la photo 0 en référence.

```text
Same pair as the reference. IDENTITY LOCK: Paul left, 29, fair skin, short salt-and-pepper hair, short beard, medium build. Nora right, 60, fair skin, short black hair above the ears, athletic. Exactly two adults. Saône quay, Lyon. Paul in an olive jacket, Nora in a long grey coat.

FACE MODE EMOJI: opaque yellow smiley on each face, no human eyes. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

### Prompt 2 — `lot10-lyonfr-0009/2.jpg`

Joindre la photo 0 en référence.

```text
Same pair as the reference. IDENTITY LOCK unchanged. Paul left, Nora right. Exactly two adults. Lyon restaurant at dusk. Paul in a white shirt, Nora in a black turtleneck.

FACE MODE EMOJI: each face covered by the opaque yellow smiley, no human facial features. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

---

## 10 — lot10-lyonfr-0010 — Mateo

- Célibataire, homme, 25 ans, né le 2001-08-22. Visage : **visible**.

Verrou : homme de 25 ans, peau foncée, visage ovale, nez droit, lèvres moyennes, yeux noisette, sourcils noirs droits. Cheveux châtains courts, bouclés souples, pas rasés. Lunettes rondes à fine monture métal doré, toujours portées, verres transparents, les yeux restent visibles. Barbe de trois jours noire, pas une barbe pleine. Silhouette athlétique, 1,80 m. Pas de tache.

### Prompt 0 — `lot10-lyonfr-0010/0.jpg`

```text
Original fictional photograph, realistic, exactly one adult man, no other person. Fully clothed, non-explicit, no nudity, no sexual pose, no logo, no readable text. Lyon cafe, daytime, waist-up, looking at the camera.

25-year-old man, dark skin, oval face, straight nose, medium lips, hazel eyes, straight black eyebrows. Short soft chestnut curls, not buzzed. Thin round gold metal glasses, clear lenses, eyes visible through them. Short black stubble, not a full beard. Athletic build. No birthmark. Black crew-neck T-shirt under an open grey overshirt.

FACE MODE VISIBLE: face sharp and fully visible through the clear glasses, no blur, no sticker, no sunglasses.
```

### Prompt 1 — `lot10-lyonfr-0010/1.jpg`

Joindre la photo 0 en référence.

```text
Same man as the reference. IDENTITY LOCK: 25, dark skin, oval face, hazel eyes, short chestnut curls, round gold glasses, black stubble, athletic build. Exactly one person. Saône quay, Lyon, dark green jacket.

FACE MODE VISIBLE: face sharp, glasses clear, no blur, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

### Prompt 2 — `lot10-lyonfr-0010/2.jpg`

Joindre la photo 0 en référence.

```text
Same man as the reference. IDENTITY LOCK unchanged, round gold glasses still on. Exactly one person. Lyon restaurant at dusk, navy button shirt.

FACE MODE VISIBLE: face sharp, no blur, no sticker. Fully clothed, non-explicit, no nudity, no logo, no readable text.
```

---

## Récapitulatif

| Compte | Nom | Type | Visage | Fichiers |
|---|---|---|---|---|
| lot10-lyonfr-0001 | Nina & Nora | couple FF | visible | 0 publique, 1 publique, 2 privée |
| lot10-lyonfr-0002 | Angel | célibataire non binaire | visible | idem |
| lot10-lyonfr-0003 | Amina | célibataire femme | visible | idem |
| lot10-lyonfr-0004 | Inès | célibataire femme | blurred | idem |
| lot10-lyonfr-0005 | Mateo & Paul | couple HH | visible | idem |
| lot10-lyonfr-0006 | Yan & Amina | couple HF | emoji | idem |
| lot10-lyonfr-0007 | Maya | célibataire femme | blurred | idem |
| lot10-lyonfr-0008 | Lucas | célibataire homme | visible | idem |
| lot10-lyonfr-0009 | Paul & Nora | couple HF | emoji | idem |
| lot10-lyonfr-0010 | Mateo | célibataire homme | visible | idem |

Ces images ne sont pas encore générées. Après création, ranger les JPEG dans ces dossiers puis assembler le lot depuis l'administration.
