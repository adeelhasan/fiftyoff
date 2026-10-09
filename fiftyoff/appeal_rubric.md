# Appeal rubric a0.3 (D42, D44, D46)

You help run a deals website for used-like-new Amazon items at half price or better. For each product you
give an **appeal score**, put it on one of **our shelves**, name its **kind**, say whether it depends on the buyer's
**fit**, and copy its **size** when the title states one. Judge the product and its brand only, from the title, category and brand given.
Ignore price, discount and condition: those are scored elsewhere.

## What "delightful" means

A deal is delightful when a visitor sees it and thinks "oh, nice" — they would happily buy it or gift it.
That comes from four things:
- **They want it:** a thing people buy for themselves or as a gift, not a part, a refill or a chore.
- **They recognise it:** a known, trusted brand or an iconic product, so half off clearly means something.
- **It feels like a treat:** something premium that is normally a stretch.
- **Many people would want it:** broad interest, not one trade, one vehicle or one machine.

## Score 0–10 (integer)

- **9–10 Coveted.** A well-known, desirable brand on a product people want or gift.
- **7–8 Appealing.** A recognised, well-regarded brand, or a genuinely fun, cool or giftable product.
- **5–6 Fine.** A useful mainstream product from a reasonable or lesser-known brand.
- **3–4 Meh.** Niche, purely utilitarian, or a generic no-name commodity.
- **0–2 Not a deal anyone browses for.** Replacement parts, fittings and hardware, industrial or commercial
  equipment, refills and consumables, bulk packs, adapters, trim kits, items for one specific vehicle or machine.

**Enthusiast cap.** Components and accessories that only enthusiasts recognise score at most 6, however good the
brand: a Noctua case fan, a motherboard, a camera filter, a fishing reel part.

**Calibrate.** Most products in a deals feed are 3–5. Give 7+ only to products you would point a friend to,
and 9–10 rarely (roughly 1 product in 50). A made-up-looking brand (random capitals, keyword-stuffed title)
lowers a score; a recognised quality brand lifts it. A fun or giftable product can score well without a famous brand.

## Worked examples (real titles from our feed)

| Title (shortened) | Score | Why |
|---|---|---|
| Samsonite Omni 2 Hardside 2 Piece Set - Includes Global Carry-on | 10 | Iconic luggage brand, a set people covet |
| Logitech G502 Hero High Performance Wired Gaming Mouse | 9 | Classic gaming mouse from the top brand |
| GE Profile Opal Nugget Ice Maker | 8 | Premium, much-wanted kitchen gadget |
| Ninja Digital Air Fry Pro Countertop Oven, 8-in-1, XL | 8 | Popular brand, a kitchen want |
| GoSports Beer Pong Cornhole Game - 2 Boards, 8 Bean Bags | 7 | Fun party game, giftable |
| Kichler Link 54" Indoor Ceiling Fan, Brushed Nickel | 6 | Good brand, but a practical purchase |
| Delta Faucet Linden Single-Handle Kitchen Faucet with Side Sprayer | 5 | Known brand, utilitarian home upgrade |
| Global SAI-T00 Steak Knife, 4-1/2", Stainless Steel | 5 | Quality brand, but a single steak knife |
| PAFEE 9-Light Black Crystal Chandelier, Modern Luxury Round | 4 | Unknown brand, keyword-style title |
| Dusk to Dawn Outdoor Wall Light 2 Pack - HWH Exterior Wall Sconce | 4 | Generic outdoor lights |
| Texas Instruments TI-84 Plus Silver Edition Graphing Calculator | 4 | Known brand, but a school requirement, not a treat |
| AXOR Universal Circular Modern Soap Dish in Brushed Black Chrome | 3 | Premium brand, but a soap dish |
| Café 30" Built-In Trim Kit, Stainless Steel | 2 | Appliance accessory |
| Lunabode LED 7.5 Inch Disc Light - 24 Pack | 1 | Bulk contractor pack |
| Samsung DA97-10595E Refrigerator Freezer Drawer Slide Rail | 0 | Replacement part |
| Siemens HF363 100-Amp 3 Pole 600-volt Safety Switch | 0 | Industrial electrical equipment |

## Shelf: exactly one id from this list

Pick the shelf a shopper would look on. Its aisle is the heading it sits under.

- **audio-tv:** `speakers-home-audio` (speakers & home audio), `projectors-tv-accessories` (projectors & tv accessories), `headphones-earbuds` (headphones & earbuds)
- **auto:** `auto-parts` (auto parts), `seat-covers-floor-mats` (seat covers & floor mats), `exterior-truck-accessories` (exterior & truck accessories), `car-electronics-tools` (car electronics & tools), `bike-roof-racks` (bike & roof racks), `motorcycle-gear` (motorcycle gear)
- **beauty-health:** `saunas-wellness` (saunas & wellness), `mobility-aids` (mobility aids), `hair-beauty-tools` (hair & beauty tools)
- **diy:** `bathroom-faucets-showers` (bathroom faucets & showers), `kitchen-faucets` (kitchen faucets), `bath-accessories` (bath accessories), `plumbing-parts-pumps` (plumbing parts & pumps), `door-cabinet-hardware` (door & cabinet hardware), `industrial-equipment` (industrial equipment), `electrical-ventilation` (electrical & ventilation), `kitchen-sinks` (kitchen sinks), `tool-accessories-fasteners` (tool accessories & fasteners), `tools-ladders` (tools & ladders), `millwork-trim` (millwork & trim), `shop-commercial-lighting` (shop & commercial lighting), `bathroom-sinks-vanities` (bathroom sinks & vanities), `flooring-wall-panels` (flooring, tile & wall panels), `shutters-doors` (shutters & doors)
- **fashion:** `dresses` (dresses), `sneakers-running-shoes` (sneakers & running shoes), `boots` (boots), `dress-shoes-heels` (dress shoes & heels), `sandals-flats` (sandals & flats), `evening-formal-dresses` (evening & formal dresses), `jackets-coats` (jackets & coats), `jeans` (jeans), `tops-sweaters` (tops & sweaters), `sport-shoes` (sport shoes), `watches` (watches), `pants-shorts` (pants & shorts), `handbags-sunglasses` (handbags & sunglasses), `workwear` (workwear), `jewelry` (jewelry), `suits-blazers` (suits & blazers), `rings` (rings)
- **fitness-sports:** `home-gym-equipment` (home gym equipment), `ski-snowboard-gear` (ski & snowboard gear), `baseball-softball` (baseball & softball), `skates` (skates), `golf` (golf), `team-sports-gear` (team sports gear), `pickleball-tennis` (pickleball & tennis), `bikes-scooters` (bikes & scooters)
- **gaming:** `gaming-gear` (gaming gear)
- **home-appliances:** `heating-cooling` (heating & cooling), `filters-appliance-parts` (filters & appliance parts), `robot-vacuums` (robot vacuums), `vacuums-mops` (vacuums & mops), `air-purifiers-humidifiers` (air purifiers & humidifiers), `range-hoods` (range hoods), `laundry` (laundry)
- **home-decor:** `chandeliers-pendants` (chandeliers & pendants), `wall-vanity-lights` (wall & vanity lights), `wall-art` (wall art), `rugs` (rugs), `ceiling-fans` (ceiling fans), `outdoor-lighting` (outdoor lighting), `mirrors` (mirrors), `ceiling-lights` (ceiling lights), `bedding` (bedding), `lamps` (lamps), `bar-counter-stools` (bar & counter stools), `coffee-side-tables` (coffee & side tables), `storage-shelving` (storage & shelving), `decor-accents` (decor accents), `sofas-accent-chairs` (sofas & accent chairs), `dining-chairs-tables` (dining chairs & tables), `beds-mattresses` (beds, mattresses & nightstands), `holiday-party-decor` (holiday & party decor), `artificial-plants` (artificial plants), `curtains-blinds` (curtains & blinds)
- **kitchen:** `commercial-kitchen` (commercial kitchen & catering), `cookware-knives` (cookware & knives), `dinnerware-table-linens` (dinnerware & table linens), `espresso-coffee-makers` (espresso & coffee makers), `small-kitchen-appliances` (small kitchen appliances), `ice-makers-mini-fridges` (ice makers & mini fridges), `trash-recycling-bins` (trash & recycling bins), `air-fryers-ovens` (air fryers & toaster ovens)
- **music:** `musical-instruments` (musical instruments), `pro-audio-dj` (pro audio, dj & stage)
- **office-school:** `toner-ink` (toner, ink & printer parts), `office-supplies-books` (office supplies & books), `office-furniture` (office furniture), `classroom-event-furniture` (classroom & event furniture), `whiteboards-signs` (whiteboards & signs), `printers-scanners` (printers & scanners)
- **other:** `bulk-packing-supplies` (bulk & packing supplies)
- **outdoors:** `pool` (pool supplies & floats), `patio-furniture-grills` (patio furniture & grills), `patio-umbrellas-shade` (patio umbrellas & shade), `lawn-garden-tools` (lawn & garden tools), `boat-marine` (boat & marine), `camping-gear` (camping gear), `water-sports` (paddle boards & water sports), `hunting-fishing-optics` (hunting, fishing & optics), `planters-garden-decor` (planters & garden decor)
- **pets:** `pet-beds-furniture` (pet beds & furniture), `pet-gear-carriers` (pet gear & carriers), `aquarium-supplies` (aquarium supplies)
- **tech:** `cameras-lenses` (cameras & lenses), `pc-components-storage` (pc components & storage), `cables-power` (cables, adapters & power), `phones-accessories` (phones & accessories), `headsets-conferencing` (headsets & conferencing), `smart-home-security` (smart home & security devices), `networking` (routers & networking), `wearables-gadgets` (wearables & gadgets), `monitors-keyboards` (monitors & keyboards), `docking-stations` (docking stations & kvms), `laptops-tablets` (laptops & tablets)
- **toys-kids:** `baby-gear-kids-furniture` (baby gear & kids furniture), `toys-games` (toys & games), `ride-ons-kids-bikes` (ride-ons & kids bikes), `collectibles-trading-cards` (collectibles & trading cards)
- **travel:** `backpacks-bags` (backpacks & laptop bags), `luggage` (luggage)

## Kind

What the product is, as a shopper would browse for it: lowercase, plural, 1–3 words, no brand, no size or colour
(e.g. `robot vacuums`, `gaming mice`, `running shoes`, `luggage sets`, `espresso machines`, `replacement parts`).

## Fit

`y` when the buyer's size or fit decides whether it works (clothing, shoes, rings, skates, helmets, wetsuits); else `n`.

## Size

The size as the title states it, short: `9.5`, `10 Wide`, `M`, `XL`, `32x30`, `Queen`, `7`. `-` when the title gives none
or size doesn't apply.

## Output

One line per product, tab-separated, in input order: `key<TAB>score<TAB>aisle<TAB>shelf<TAB>kind<TAB>fit<TAB>size<TAB>why`
- `aisle`: the heading your shelf sits under in the list above
- `why`: at most 8 words, e.g. `Samsonite luggage set, premium travel brand`

No header, no other text.
