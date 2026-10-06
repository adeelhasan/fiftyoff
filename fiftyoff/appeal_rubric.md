# Appeal rubric a0.1 (D42)

You rate how **delighted a typical US shopper browsing a deals site** would be to find each product
at **half price**. Judge the product and its brand only, from the title, category and brand given.
Ignore price, discount and condition: those are scored elsewhere.

## Score 0–10 (integer)

- **9–10** Coveted: a well-known, desirable brand on a product people want or gift.
  Samsonite luggage set, Dyson vacuum, Apple, Bose headphones, LEGO set, Le Creuset, Nintendo, KitchenAid mixer.
- **7–8** Appealing: a recognised, well-regarded brand, or a genuinely fun, cool or giftable product.
  Logitech gaming mouse, Ninja blender, a popular toy, Yeti tumbler, a nice espresso machine.
- **5–6** Fine: a useful mainstream consumer product, from a reasonable or lesser-known brand.
  An ordinary lamp, a decent office chair, a mid-range kitchen gadget.
- **3–4** Meh: niche, purely utilitarian, or a generic no-name commodity.
- **0–2** Not a deal anyone browses for: replacement parts, fittings and hardware, industrial or commercial
  equipment, refills and consumables, bulk packs, adapters, mounting kits, items for one specific vehicle or machine.

Brand matters: a recognised quality brand lifts a score; a made-up-looking brand (random capitals,
keyword-stuffed title) lowers it. Products can be appealing without a famous brand if they are fun or giftable.

## Tags

1–2 interest tags from exactly this list: `tech`, `gaming`, `audio`, `home`, `kitchen`, `outdoors`, `fitness`,
`travel`, `toys`, `fashion`, `beauty`, `tools`, `auto`, `pets`, `office`, `garden`, `music`, `baby`, `health`.

## Output

One line per product, tab-separated, in input order: `key<TAB>score<TAB>tags<TAB>why`
- `tags`: comma-separated, no spaces
- `why`: at most 8 words, e.g. `Samsonite luggage set, premium travel brand`

No header, no other text.
