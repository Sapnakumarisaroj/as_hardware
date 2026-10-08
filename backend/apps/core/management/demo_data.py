"""DEVELOPMENT / DEMO SEED DATA — not real products, prices or stock.

Brands are fictional and suffixed "(Demo)", except "Fevicol": the owner's approved category is the
Fevicol brand itself, so its products carry that real brand name with illustrative demo prices.
Every SKU starts with "DEMO-"; every store code starts with "DEMO-". Prices are illustrative only.
The category tree is the owner's approved taxonomy (`apps.catalog.taxonomy`) and is also used in
production (`manage.py apply_taxonomy`).
"""

from apps.catalog.taxonomy import APPROVED_TAXONOMY

# Top level → children ("slug", "Name"). Single source: apps/catalog/taxonomy.py.
CATEGORIES = APPROVED_TAXONOMY

BRANDS = [
    "ForgePro (Demo)",
    "BuildMax (Demo)",
    "SafeGuard (Demo)",
    "WoodCore (Demo)",
    "FitWell (Demo)",
    "LockSure (Demo)",
    "ClearEdge (Demo)",
    "Fevicol",
]

# (category, subcategory, name, brand, unit, gst, tags, variants, specs)
# variants: (sku_suffix, variant_name, mrp, price, weight_g)
# specs: (name, value, unit)
# A product is found again by its first variant's SKU, so keep that suffix stable.
PRODUCTS = [
    # --- Plywood, MDF & HDHMR ---------------------------------------------------------------------
    (
        "plywood-mdf-hdhmr",
        "plywood",
        "BWP Marine Plywood, 8 x 4 ft",
        "WoodCore (Demo)",
        "piece",
        "18",
        ["plywood", "ply", "marine plywood", "bwp", "kitchen", "wardrobe"],
        [
            ("PLY-BWP-12", "12 mm", "3600", "2990", 26000),
            ("PLY-BWP-18", "18 mm", "4950", "4190", 38000),
            ("PLY-BWP-6", "6 mm", "2100", "1750", 13000),
        ],
        [
            ("Grade", "BWP (IS 710)", ""),
            ("Size", "8 x 4", "ft"),
            ("Core", "Hardwood", ""),
            ("Water Resistance", "Boiling water proof", ""),
        ],
    ),
    (
        "plywood-mdf-hdhmr",
        "plywood",
        "MR Grade Commercial Plywood, 8 x 4 ft",
        "WoodCore (Demo)",
        "piece",
        "18",
        ["plywood", "ply", "mr grade", "commercial plywood", "furniture"],
        [("PLY-MR-12", "12 mm", "2400", "1990", 25000), ("PLY-MR-18", "18 mm", "3300", "2790", 37000)],
        [("Grade", "MR (IS 303)", ""), ("Size", "8 x 4", "ft"), ("Use", "Interior furniture", "")],
    ),
    (
        "plywood-mdf-hdhmr",
        "mdf",
        "Plain MDF Board, 8 x 4 ft",
        "WoodCore (Demo)",
        "piece",
        "18",
        ["mdf", "mdf board", "board", "furniture"],
        [("MDF-12", "12 mm", "1650", "1390", 24000), ("MDF-18", "18 mm", "2300", "1960", 35000)],
        [("Density", "730", "kg/m³"), ("Size", "8 x 4", "ft"), ("Use", "Interior, dry areas", "")],
    ),
    (
        "plywood-mdf-hdhmr",
        "hdhmr",
        "HDHMR Board, 8 x 4 ft",
        "WoodCore (Demo)",
        "piece",
        "18",
        ["hdhmr", "hdhmr board", "high density", "kitchen", "board"],
        [("HDHMR-18", "18 mm", "3400", "2890", 42000), ("HDHMR-12", "12 mm", "2500", "2120", 29000)],
        [("Density", "850", "kg/m³"), ("Size", "8 x 4", "ft"), ("Moisture Resistance", "High", "")],
    ),
    # --- Fevicol (brand-led category) --------------------------------------------------------------
    (
        "fevicol",
        "fevicol-wood-adhesives",
        "Fevicol SH Synthetic Resin Wood Adhesive",
        "Fevicol",
        "piece",
        "18",
        ["fevicol", "glue", "wood adhesive", "furniture", "carpentry"],
        [
            ("WOODADH-1", "1 kg", "340", "279", 1000),
            ("FEVI-SH-500", "500 g", "185", "159", 500),
            ("FEVI-SH-5", "5 kg", "1550", "1349", 5000),
        ],
        [("Type", "Synthetic resin (PVA)", ""), ("Use", "Wood to wood, laminates, plywood", "")],
    ),
    (
        "fevicol",
        "fevicol-contact-adhesives",
        "Fevicol Heatx Contact Adhesive",
        "Fevicol",
        "piece",
        "18",
        ["fevicol", "contact adhesive", "laminate", "sunmica", "glue"],
        [("FEVI-HX-1", "1 L", "620", "529", 950), ("FEVI-HX-500", "500 ml", "335", "289", 480)],
        [("Type", "Synthetic rubber contact", ""), ("Use", "Laminates, veneer, foam", "")],
    ),
    (
        "fevicol",
        "fevicol-waterproof-adhesives",
        "Fevicol Marine Waterproof Wood Adhesive",
        "Fevicol",
        "piece",
        "18",
        ["fevicol", "marine", "waterproof adhesive", "wood adhesive", "kitchen"],
        [("FEVI-MAR-1", "1 kg", "560", "479", 1000)],
        [("Type", "Waterproof PVA", ""), ("Use", "Kitchens, bathrooms, outdoor furniture", "")],
    ),
    # --- Hinges, Channels & Handles ----------------------------------------------------------------
    (
        "hinges-channels-handles",
        "hinges",
        "Soft-Close Concealed Hinge, Full Overlay (Pair)",
        "FitWell (Demo)",
        "pair",
        "18",
        ["hinge", "concealed hinge", "auto hinge", "soft close", "cabinet", "kabja"],
        [("HNG-SC-FO", "Full overlay", "420", "329", 220), ("HNG-SC-HO", "Half overlay", "420", "329", 220)],
        [
            ("Cup Diameter", "35", "mm"),
            ("Opening Angle", "105", "°"),
            ("Finish", "Nickel", ""),
            ("Mechanism", "Soft close", ""),
        ],
    ),
    (
        "hinges-channels-handles",
        "hinges",
        "Stainless Steel Butt Hinge 4 inch (Pack of 2)",
        "FitWell (Demo)",
        "pack",
        "18",
        ["hinge", "butt hinge", "door hinge", "kabja"],
        [("HNG-BUTT-4", "", "260", "199", 260)],
        [("Length", "100", "mm"), ("Material", "SS 304", ""), ("Pack Size", "2", "pcs")],
    ),
    (
        "hinges-channels-handles",
        "drawer-channels",
        "Telescopic Ball-Bearing Drawer Channel (Pair)",
        "FitWell (Demo)",
        "pair",
        "18",
        ["drawer channel", "drawer slide", "telescopic channel", "drawer"],
        [
            ("CH-TEL-18", "18 inch", "520", "399", 1300),
            ("CH-TEL-12", "12 inch", "380", "299", 900),
            ("CH-TEL-24", "24 inch", "690", "549", 1700),
        ],
        [("Extension", "Full", ""), ("Load Capacity", "35", "kg"), ("Finish", "Zinc", "")],
    ),
    (
        "hinges-channels-handles",
        "cabinet-handles",
        "Aluminium Profile Cabinet Handle",
        "FitWell (Demo)",
        "piece",
        "18",
        ["handle", "cabinet handle", "drawer handle", "kitchen handle"],
        [("HDL-AL-160", "160 mm", "240", "189", 120), ("HDL-AL-224", "224 mm", "300", "239", 160)],
        [("Material", "Aluminium", ""), ("Finish", "Matt black", "")],
    ),
    # --- Kitchen Systems & Accessories ---------------------------------------------------------------
    (
        "kitchen-systems",
        "kitchen-baskets",
        "Stainless Steel Cutlery Basket",
        "FitWell (Demo)",
        "piece",
        "18",
        ["kitchen basket", "cutlery basket", "modular kitchen", "drawer"],
        [
            ("BSK-CUT-15", "15 inch cabinet", "2150", "1690", 2600),
            ("BSK-CUT-18", "18 inch cabinet", "2450", "1940", 3000),
        ],
        [("Material", "SS 304", ""), ("Height", "150", "mm")],
    ),
    (
        "kitchen-systems",
        "kitchen-tall-units",
        "Pull-Out Pantry Unit, 5 Shelves",
        "FitWell (Demo)",
        "piece",
        "18",
        ["pantry unit", "tall unit", "modular kitchen"],
        [("PAN-5-450", "450 mm cabinet", "16500", "13490", 21000)],
        [("Shelves", "5", ""), ("Cabinet Width", "450", "mm"), ("Material", "Powder-coated steel", "")],
    ),
    (
        "kitchen-systems",
        "kitchen-accessories",
        "Plate and Thali Organiser Basket",
        "FitWell (Demo)",
        "piece",
        "18",
        ["plate basket", "thali basket", "modular kitchen"],
        [("BSK-PLT-24", "24 inch cabinet", "2850", "2290", 3400)],
        [("Material", "SS 304", ""), ("Holds", "Plates and thalis", "")],
    ),
    # --- Wardrobe & Bed Fittings ---------------------------------------------------------------------
    (
        "wardrobe-bed-fittings",
        "wardrobe-fittings",
        "Wardrobe Hanging Rail with End Supports",
        "FitWell (Demo)",
        "set",
        "18",
        ["wardrobe rail", "hanger rod", "wardrobe", "almirah"],
        [("WR-RAIL-4", "4 ft", "420", "329", 900), ("WR-RAIL-3", "3 ft", "350", "279", 700)],
        [("Material", "Aluminium oval tube", ""), ("Finish", "Silver", "")],
    ),
    (
        "wardrobe-bed-fittings",
        "wardrobe-fittings",
        "Sliding Wardrobe Door Fitting Set",
        "FitWell (Demo)",
        "set",
        "18",
        ["sliding door", "wardrobe", "almirah", "sliding fitting"],
        [("WR-SLD-2D", "2 doors", "2650", "2190", 4200)],
        [("Door Weight", "Up to 40", "kg"), ("Track Length", "6", "ft")],
    ),
    (
        "wardrobe-bed-fittings",
        "bed-fittings",
        "Hydraulic Bed Lift Mechanism (Pair)",
        "FitWell (Demo)",
        "pair",
        "18",
        ["bed fitting", "hydraulic bed", "storage bed", "bed"],
        [("BED-HYD-PR", "", "3600", "2890", 6500)],
        [("Lift Capacity", "Up to 100", "kg"), ("Mechanism", "Gas spring", "")],
    ),
    (
        "wardrobe-bed-fittings",
        "bed-fittings",
        "Bed Fitting Bracket Set (4 pcs)",
        "FitWell (Demo)",
        "set",
        "18",
        ["bed fitting", "bed bracket", "bed"],
        [("BED-BRK-4", "", "380", "299", 800)],
        [("Pieces", "4", ""), ("Material", "Mild steel", "")],
    ),
    # --- Door Locks & Hardware -----------------------------------------------------------------------
    (
        "door-locks-hardware",
        "door-locks",
        "Mortise Door Lock with Lever Handles",
        "LockSure (Demo)",
        "set",
        "18",
        ["door lock", "mortise lock", "lock", "taala", "handle"],
        [("LCK-MOR-SS", "Satin steel", "2450", "1890", 2200), ("LCK-MOR-AB", "Antique brass", "2650", "2090", 2200)],
        [("Keys", "3", ""), ("Lock Body", "Mortise", ""), ("Door Thickness", "35 - 45", "mm")],
    ),
    (
        "door-locks-hardware",
        "door-locks",
        "Cylindrical Knob Lock, Bedroom",
        "LockSure (Demo)",
        "piece",
        "18",
        ["knob lock", "door lock", "lock", "bedroom lock"],
        [("LCK-KNOB-BR", "", "990", "749", 700)],
        [("Function", "Privacy (bedroom)", ""), ("Finish", "Stainless steel", "")],
    ),
    (
        "door-locks-hardware",
        "door-hardware",
        "Hydraulic Door Closer",
        "LockSure (Demo)",
        "piece",
        "18",
        ["door closer", "hydraulic closer"],
        [("CLS-HYD-60", "Up to 60 kg door", "1450", "1090", 1500)],
        [("Door Weight", "Up to 60", "kg"), ("Speed", "Adjustable", "")],
    ),
    (
        "door-locks-hardware",
        "door-hardware",
        "Tower Bolt 8 inch",
        "LockSure (Demo)",
        "piece",
        "18",
        ["tower bolt", "door bolt", "latch"],
        [("TB-8-SS", "", "190", "139", 250)],
        [("Length", "200", "mm"), ("Material", "Stainless steel", "")],
    ),
    # --- Power Tools & Accessories -------------------------------------------------------------------
    (
        "power-tools",
        "drills",
        "Corded Impact Drill 650W, 13 mm",
        "ForgePro (Demo)",
        "piece",
        "18",
        ["drill", "impact", "concrete"],
        [("DRILL-650", "", "4299", "3299", 1800)],
        [
            ("Power", "650", "W"),
            ("Chuck Size", "13", "mm"),
            ("No-load Speed", "3000", "RPM"),
            ("Voltage", "230", "V"),
            ("Impact Function", "Yes", ""),
        ],
    ),
    (
        "power-tools",
        "drills",
        "Cordless Drill Driver 12V",
        "ForgePro (Demo)",
        "piece",
        "18",
        ["drill", "cordless"],
        [("DRILL-12V", "", "5499", "4299", 1100)],
        [("Voltage", "12", "V"), ("Chuck Size", "10", "mm"), ("Battery", "2.0 Ah Li-ion", ""), ("Torque", "30", "Nm")],
    ),
    (
        "power-tools",
        "drill-bits",
        "Masonry Drill Bit Set (5 pcs)",
        "ForgePro (Demo)",
        "set",
        "18",
        ["drill bit", "masonry", "concrete"],
        [("BIT-MAS-5", "", "450", "329", 200)],
        [("Sizes", "5, 6, 8, 10, 12", "mm"), ("Material", "Carbide tipped", ""), ("Shank", "Round", "")],
    ),
    (
        "power-tools",
        "drill-bits",
        "HSS Metal Drill Bit Set (13 pcs)",
        "ForgePro (Demo)",
        "set",
        "18",
        ["drill bit", "metal"],
        [("BIT-HSS-13", "", "799", "599", 250)],
        [("Sizes", "1.5 - 6.5", "mm"), ("Material", "HSS", "")],
    ),
    (
        "power-tools",
        "grinders",
        "Angle Grinder 850W, 100 mm",
        "ForgePro (Demo)",
        "piece",
        "18",
        ["angle grinder", "grinder", "cutting", "polishing"],
        [("GRND-850", "", "3999", "2899", 1900)],
        [("Power", "850", "W"), ("Disc Diameter", "100", "mm"), ("No-load Speed", "11000", "RPM")],
    ),
    # --- General Hardware & Tools --------------------------------------------------------------------
    (
        "general-hardware",
        "screwdrivers",
        "Screwdriver Set (6 pcs), Magnetic Tips",
        "ForgePro (Demo)",
        "set",
        "18",
        ["screwdriver"],
        [("SD-SET-6", "", "499", "379", 400)],
        [("Pieces", "6", ""), ("Tip", "Magnetic", "")],
    ),
    (
        "general-hardware",
        "hammers",
        "Claw Hammer, Fibreglass Handle",
        "ForgePro (Demo)",
        "piece",
        "18",
        ["hammer"],
        [("HAM-CLAW-450", "450 g", "560", "429", 650)],
        [("Head Weight", "450", "g"), ("Handle", "Fibreglass", "")],
    ),
    (
        "general-hardware",
        "spanners",
        "Double Open-End Spanner Set (8 pcs)",
        "ForgePro (Demo)",
        "set",
        "18",
        ["spanner"],
        [("SPN-8", "", "899", "649", 1200)],
        [("Sizes", "6 - 22", "mm"), ("Material", "Chrome vanadium", "")],
    ),
    (
        "general-hardware",
        "spanners",
        "Adjustable Pipe Wrench 14 inch",
        "ForgePro (Demo)",
        "piece",
        "18",
        ["pipe wrench", "wrench"],
        [("PW-14", "", "690", "529", 900)],
        [("Length", "350", "mm"), ("Max Jaw Opening", "50", "mm")],
    ),
    (
        "general-hardware",
        "measuring-tools",
        "Measuring Tape 5 m",
        "ForgePro (Demo)",
        "piece",
        "18",
        ["measuring tape"],
        [("TAPE-5M", "", "220", "159", 200)],
        [("Length", "5", "m"), ("Blade Width", "19", "mm")],
    ),
    (
        "general-hardware",
        "cutting-tools",
        "Hacksaw Frame with Blade",
        "ForgePro (Demo)",
        "piece",
        "18",
        ["hacksaw", "cutting"],
        [("HACKSAW-12", "", "350", "259", 500)],
        [("Blade Length", "300", "mm")],
    ),
    (
        "general-hardware",
        "fasteners",
        "Wood Screws, Countersunk (Box of 100)",
        "BuildMax (Demo)",
        "box",
        "18",
        ["screw", "wood screw"],
        [("SCR-8x25", "No. 8 x 25 mm", "180", "129", 300), ("SCR-8x38", "No. 8 x 38 mm", "220", "159", 420)],
        [("Head", "Countersunk", ""), ("Drive", "Phillips", ""), ("Pack Size", "100", "pcs")],
    ),
    (
        "general-hardware",
        "fasteners",
        "Nylon Wall Plugs 6 mm (Pack of 100)",
        "BuildMax (Demo)",
        "pack",
        "18",
        ["wall plug", "rawl plug", "anchor"],
        [("PLUG-6-100", "", "120", "89", 150)],
        [("Diameter", "6", "mm"), ("Pack Size", "100", "pcs")],
    ),
    (
        "general-hardware",
        "fasteners",
        "Hex Bolt with Nut, M8 x 50 (Pack of 20)",
        "BuildMax (Demo)",
        "pack",
        "18",
        ["bolt", "nut"],
        [("BOLT-M8-50", "", "260", "199", 700)],
        [("Thread", "M8", ""), ("Length", "50", "mm"), ("Finish", "Zinc plated", "")],
    ),
    (
        "general-hardware",
        "sealants",
        "Silicone Sealant, Clear, 280 ml",
        "BuildMax (Demo)",
        "piece",
        "18",
        ["silicone", "sealant", "waterproof", "glass"],
        [("SIL-280", "", "320", "239", 320)],
        [("Volume", "280", "ml"), ("Colour", "Clear", ""), ("Cure Time", "24", "h")],
    ),
    (
        "general-hardware",
        "sealants",
        "Sandpaper Sheets (Pack of 10)",
        "BuildMax (Demo)",
        "pack",
        "18",
        ["sandpaper", "emery paper", "regmal", "wood finishing"],
        [("SAND-10", "Grit 120", "150", "99", 120)],
        [("Pack Size", "10", "pcs"), ("Grit", "120", "")],
    ),
    # --- Safety Tools & Workwear ---------------------------------------------------------------------
    (
        "safety",
        "gloves",
        "Cut-Resistant Work Gloves",
        "SafeGuard (Demo)",
        "pair",
        "5",
        ["gloves"],
        [("GLV-CUT-L", "Large", "299", "219", 100)],
        [("Cut Level", "5", ""), ("Size", "L", "")],
    ),
    (
        "safety",
        "helmets",
        "Safety Helmet with Ratchet",
        "SafeGuard (Demo)",
        "piece",
        "18",
        ["helmet"],
        [("HLM-RATCHET-Y", "Yellow", "399", "289", 400)],
        [("Material", "HDPE", ""), ("Adjustment", "Ratchet", "")],
    ),
    (
        "safety",
        "masks",
        "N95 Respirator Mask (Pack of 5)",
        "SafeGuard (Demo)",
        "pack",
        "5",
        ["mask", "dust"],
        [("MASK-N95-5", "", "350", "249", 60)],
        [("Filtration", "N95", ""), ("Pack Size", "5", "pcs")],
    ),
    (
        "safety",
        "safety-shoes",
        "Steel Toe Safety Shoes",
        "SafeGuard (Demo)",
        "pair",
        "18",
        ["safety shoes"],
        [("SHOE-ST-8", "UK 8", "1499", "1149", 1300), ("SHOE-ST-9", "UK 9", "1499", "1149", 1350)],
        [("Toe Cap", "Steel", ""), ("Sole", "PU, anti-slip", "")],
    ),
    (
        "safety",
        "protective-equipment",
        "Safety Goggles, Anti-Fog",
        "SafeGuard (Demo)",
        "piece",
        "18",
        ["goggles"],
        [("GOG-AF", "", "199", "139", 80)],
        [("Lens", "Polycarbonate", ""), ("Anti-fog", "Yes", "")],
    ),
    (
        "safety",
        "workwear",
        "High-Visibility Reflective Safety Vest",
        "SafeGuard (Demo)",
        "piece",
        "5",
        ["safety vest", "reflective jacket", "workwear", "hi vis"],
        [("VEST-HV-OR", "Orange, free size", "249", "179", 150)],
        [("Colour", "Fluorescent orange", ""), ("Reflective Tape", "50", "mm")],
    ),
    # --- Glass Door Hardware -------------------------------------------------------------------------
    (
        "glass-door-hardware",
        "patch-fittings",
        "Glass Door Patch Fitting Set (Top + Bottom)",
        "ClearEdge (Demo)",
        "set",
        "18",
        ["patch fitting", "glass door", "toughened glass"],
        [("PATCH-SET-SS", "Satin steel", "3950", "3190", 2600)],
        [("Glass Thickness", "10 - 12", "mm"), ("Material", "SS 304", "")],
    ),
    (
        "glass-door-hardware",
        "glass-door-handles",
        "Glass Door Pull Handle, Back-to-Back",
        "ClearEdge (Demo)",
        "piece",
        "18",
        ["glass door handle", "pull handle", "glass door"],
        [("GDH-600", "600 mm", "2350", "1890", 1800), ("GDH-450", "450 mm", "1950", "1550", 1400)],
        [("Material", "SS 304", ""), ("Glass Thickness", "8 - 12", "mm"), ("Finish", "Satin", "")],
    ),
    (
        "glass-door-hardware",
        "floor-springs",
        "Floor Spring for Glass Doors",
        "ClearEdge (Demo)",
        "piece",
        "18",
        ["floor spring", "glass door", "door closer"],
        [("FSP-100", "Up to 100 kg door", "6800", "5490", 7500)],
        [("Door Weight", "Up to 100", "kg"), ("Hold Open", "90", "°")],
    ),
]

# code, name, kind, area, postal code, lat, lng (Bengaluru, the shop's delivery city)
STORES = [
    ("DEMO-BLR-JYN", "Demo Store — Jayanagar", "store", "Jayanagar", "560041", "12.925000", "77.593800"),
    ("DEMO-BLR-IND", "Demo Dark Store — Indiranagar", "dark_store", "Indiranagar", "560038", "12.971900", "77.641200"),
    ("DEMO-BLR-WH1", "Demo Warehouse — Peenya", "warehouse", "Peenya", "560058", "13.028500", "77.519700"),
]
STORE_CITY = ("Bengaluru", "Karnataka")
# Earlier demo stores (Pune). Re-seeding switches them off (never deletes: old orders point at them).
LEGACY_STORE_CODES = ("DEMO-PUN-KTH", "DEMO-PUN-BNR", "DEMO-PUN-WH1")

# Delivery settings of the demo stores (Phase 9): the store is open 8 am to 8 pm like the header strip says.
_DAILY_8_TO_20 = {day: ["08:00", "20:00"] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
STORE_DELIVERY = {
    "DEMO-BLR-JYN": {
        "avg_prep_minutes": 10,
        "prep_minutes_per_item": 2,
        "own_riders": 2,
        "opening_hours": _DAILY_8_TO_20,
    },
    # A dark store picks orders round the clock ({} = always open).
    "DEMO-BLR-IND": {"avg_prep_minutes": 8, "prep_minutes_per_item": 1, "own_riders": 1, "opening_hours": {}},
}

# store code, zone name, radius km, PIN codes always served, fast delivery, fast cutoff (min), fee, free from
# (None = global setting), city-wide service area (None = radius / PIN list only). Both stores serve all of
# Bengaluru; whether an order is fast is decided per address by the ETA engine (distance, riders, hours).
ZONES = [
    ("DEMO-BLR-JYN", "Bengaluru city-wide (Jayanagar)", "6", "", True, None, None, None, "Bengaluru"),
    ("DEMO-BLR-IND", "Bengaluru city-wide (Indiranagar)", "6", "", True, 45, "30", "399", "Bengaluru"),
]

# Approximate centres of some Bengaluru PIN codes (demo values for distance estimates, not survey data).
# Coverage doesn't depend on this list: every 560xxx PIN is inside the Bengaluru service area.
# postal code, area, lat, lng
PIN_CODES = [
    ("560001", "MG Road / Bengaluru GPO", "12.976600", "77.599300"),
    ("560009", "Gandhinagar (Majestic)", "12.977000", "77.572000"),
    ("560025", "Richmond Town", "12.965000", "77.600000"),
    ("560024", "Hebbal", "13.035800", "77.597000"),
    ("560064", "Yelahanka", "13.100700", "77.596300"),
    ("560092", "Sahakar Nagar", "13.062300", "77.587100"),
    ("560041", "Jayanagar", "12.925000", "77.593800"),
    ("560011", "Jayanagar 3rd Block", "12.932000", "77.583000"),
    ("560070", "Banashankari", "12.925500", "77.546800"),
    ("560078", "JP Nagar", "12.906300", "77.585700"),
    ("560100", "Electronic City", "12.845200", "77.660200"),
    ("560038", "Indiranagar", "12.971900", "77.641200"),
    ("560008", "HAL / Old Airport Road", "12.960000", "77.648000"),
    ("560037", "Marathahalli", "12.956900", "77.701100"),
    ("560066", "Whitefield", "12.969800", "77.750000"),
    ("560010", "Rajajinagar", "12.991000", "77.552000"),
    ("560040", "Vijayanagar", "12.971900", "77.537600"),
    ("560058", "Peenya", "13.028500", "77.519700"),
]

# Automatic offers (Phase 6). name, description, type, value, max_discount, min_order, priority, category slugs
# (empty = whole cart). All clearly marked "Demo".
OFFERS = [
    (
        "Demo: Power tools week",
        "Demo offer: 10% off Power Tools & Accessories (up to ₹400) when they total ₹1,500 or more.",
        "percent",
        "10",
        "400",
        "1500",
        10,
        ["power-tools"],
    ),
    (
        "Demo: Safety first",
        "Demo offer: ₹50 off Safety Tools & Workwear on ₹500 or more.",
        "fixed",
        "50",
        None,
        "500",
        20,
        ["safety"],
    ),
    (
        "Demo: Kitchen fittings",
        "Demo offer: 5% off hinges, drawer channels and kitchen baskets.",
        "percent",
        "5",
        None,
        "0",
        30,
        ["hinges", "drawer-channels", "kitchen-baskets"],
    ),
]

# code, description, type, value, max_discount, min_order
COUPONS = [
    ("DEMO10", "Demo coupon: 10% off up to ₹200 on orders above ₹500", "percent", "10", "200", "500"),
    ("DEMOFLAT50", "Demo coupon: ₹50 off on orders above ₹299", "fixed", "50", None, "299"),
]


# --- Phase 15 demo commerce data (all marked "Demo") --------------------------------------------------

# Option types: (name, unit, category slugs, [values])
OPTION_TYPES = [
    ("Thickness", "mm", ["plywood", "mdf", "hdhmr"], ["6 mm", "12 mm", "18 mm"]),
    ("Board size", "ft", ["plywood", "mdf", "hdhmr"], ["8 x 4 ft"]),
    ("Channel length", "inch", ["drawer-channels"], ["12 inch", "18 inch", "24 inch"]),
    (
        "Pack size",
        "",
        ["fevicol-wood-adhesives", "fevicol-contact-adhesives"],
        ["500 g", "500 ml", "1 kg", "1 L", "5 kg"],
    ),
]

# Variant options: sku suffix → {option name: value}
VARIANT_OPTIONS = {
    **{
        f"{code}-{mm}": {"Thickness": f"{mm} mm", "Board size": "8 x 4 ft"}
        for code, sizes in {"PLY-BWP": (6, 12, 18), "PLY-MR": (12, 18), "MDF": (12, 18), "HDHMR": (12, 18)}.items()
        for mm in sizes
    },
    **{f"CH-TEL-{inch}": {"Channel length": f"{inch} inch"} for inch in (12, 18, 24)},
    "WOODADH-1": {"Pack size": "1 kg"},
    "FEVI-SH-500": {"Pack size": "500 g"},
    "FEVI-SH-5": {"Pack size": "5 kg"},
    "FEVI-HX-1": {"Pack size": "1 L"},
    "FEVI-HX-500": {"Pack size": "500 ml"},
}

# Bulk prices: sku suffix → [(from quantity, unit price)]
PRICE_TIERS = {
    "PLY-BWP-18": [(10, "4090"), (25, "3990")],
    "PLY-MR-18": [(10, "2720"), (25, "2650")],
    "MDF-18": [(10, "1910")],
    "HNG-SC-FO": [(10, "315"), (25, "299")],
    "CH-TEL-18": [(10, "379"), (25, "365")],
    "WOODADH-1": [(5, "269"), (10, "259")],
    "SCR-8x25": [(5, "119")],
}

# Products launched recently (sku suffix of the first variant → days ago), for "New launches".
LAUNCHES = {"HDHMR-18": 3, "GRND-850": 10}

# Curated lists: (name, rule, description, days valid or None, [first-variant sku suffixes for manual lists])
COLLECTIONS = [
    ("Demo: Deals of the week", "manual", "Demo list: this week's picks.", 7, ["PLY-BWP-12", "HNG-SC-FO", "CH-TEL-18"]),
    ("Demo: Best sellers", "best_sellers", "Demo list: most units sold in the last 30 days.", None, []),
    ("Demo: New launches", "new_launches", "Demo list: launched in the last 60 days.", None, []),
    ("Demo: Carpentry essentials", "manual", "Demo list: basics for furniture work.", None,
     ["WOODADH-1", "SCR-8x25", "HNG-BUTT-4", "SD-SET-6"]),
    ("Demo: Bulk buying", "bulk_pricing", "Demo list: products with bulk prices.", None, []),
]  # fmt: skip

# Free-delivery rules: (name, threshold, category slugs)
FREE_DELIVERY_RULES = [("Demo: Free delivery on plywood and boards from ₹5,000", "5000", ["plywood-mdf-hdhmr"])]

# Phase 15 offers: dicts with the new conditions.
OFFERS_PHASE15 = [
    {
        "name": "Demo: First order delivers free",
        "description": "Demo offer: free delivery on your first order.",
        "benefit": "free_delivery",
        "max_prior_orders": 0,
        "priority": 40,
        "categories": [],
    },
    {
        "name": "Demo: Gloves 10+",
        "description": "Demo offer: 5% off gloves when you buy 10 or more of one kind.",
        "discount_type": "percent",
        "value": "5",
        "min_quantity": 10,
        "priority": 15,
        "categories": ["gloves"],
    },
    {
        "name": "Demo: Festive door hardware",
        "description": "Demo festival offer: 8% off door locks and door hardware, up to ₹150.",
        "discount_type": "percent",
        "value": "8",
        "max_discount_amount": "150",
        "campaign": "Festive (demo)",
        "per_customer_limit": 2,
        "priority": 25,
        "categories": ["door-locks-hardware"],
    },
]


# --- Phase 16 demo product-page content and accessories --------------------------------------------------
# General product guidance for the demo catalogue (no ratings, counts or claims about sales).

# first-variant sku suffix → {quick_answer, uses, installation_steps, faqs}
PRODUCT_PAGE_CONTENT = {
    "PLY-BWP-12": {
        "quick_answer": "Boiling-water-proof plywood for kitchens, bathrooms and other damp areas.",
        "uses": "Modular kitchen carcasses and shutters\nBathroom vanities\nWardrobes in damp rooms",
        "installation_steps": (
            "Store sheets flat, off the floor, in a dry place\n"
            "Mark and cut with a fine-tooth saw, good face up\n"
            "Seal cut edges with edge banding or laminate\n"
            "Fix with wood screws and a waterproof wood adhesive"
        ),
        "faqs": [
            {
                "question": "BWP or MR plywood for a kitchen?",
                "answer": "BWP (boiling water proof) is the usual choice for kitchens and bathrooms; MR plywood "
                "suits dry rooms such as bedrooms and living rooms.",
            }
        ],
    },
    "DRILL-650": {
        "quick_answer": "Corded impact drill for holes in brick, concrete, wood and metal.",
        "uses": "Drilling brick and concrete walls (impact mode)\nWood and metal (normal mode)\nFixing wall plugs",
        "installation_steps": (
            "Choose the right bit: masonry for walls, HSS for metal\n"
            "Mark the spot and wear safety glasses\n"
            "Switch impact mode on only for brick and concrete\n"
            "Start slowly, then increase speed while keeping the drill straight"
        ),
        "faqs": [
            {
                "question": "Can it drill into concrete?",
                "answer": "Yes, with a masonry bit and impact mode switched on.",
            }
        ],
    },
    "HNG-SC-FO": {
        "quick_answer": "Soft-close concealed hinge for kitchen and wardrobe shutters.",
        "uses": "Kitchen cabinet shutters\nWardrobe doors\nVanity cabinets",
        "installation_steps": (
            "Drill a 35 mm cup hole in the shutter with a Forstner bit\n"
            "Press the hinge cup in and fix it with two screws\n"
            "Fix the mounting plate on the cabinet side\n"
            "Clip the hinge on and adjust height, depth and side screws"
        ),
        "faqs": [
            {
                "question": "Full overlay or half overlay?",
                "answer": "Full overlay when the shutter covers the whole side panel; half overlay when two shutters "
                "share one panel.",
            }
        ],
    },
}

# first-variant sku suffix → [(accessory first-variant sku suffix, note)]
ACCESSORIES = {
    "DRILL-650": [
        ("BIT-MAS-5", "For brick and concrete"),
        ("BIT-HSS-13", "For metal"),
        ("PLUG-6-100", "To fix screws in walls"),
    ],
    "DRILL-12V": [("BIT-HSS-13", "For metal and wood"), ("PLUG-6-100", "To fix screws in walls")],
    "HNG-SC-FO": [("SCR-8x25", "Screws for the hinge plates"), ("SD-SET-6", "To fit and adjust")],
    "CH-TEL-18": [("SCR-8x25", "Screws for the channels"), ("HDL-AL-160", "Drawer handle")],
    "PLY-BWP-12": [("WOODADH-1", "Wood adhesive for joints"), ("FEVI-MAR-1", "Waterproof adhesive for wet areas")],
}

# Phase 22 smart shopping: bundles (name, kind, description, promo label, [(sku suffix, quantity, optional, note)])
BUNDLES = [
    (
        "Demo: Wall drilling kit",
        "drilling",
        "Demo kit: drill concrete or brick and fix shelves.",
        "Starter kit",
        [
            ("DRILL-650", 1, False, ""),
            ("BIT-MAS-5", 1, False, "Carbide bits for walls"),
            ("PLUG-6-100", 1, False, ""),
            ("SCR-8X25", 1, False, "Fits the 6 mm plugs"),
            ("GOG-AF", 1, True, "Protect your eyes"),
        ],
    ),
    (
        "Demo: Kitchen drawer kit",
        "custom",
        "Demo kit: fit one kitchen drawer with soft running channels and a handle.",
        "",
        [
            ("CH-TEL-18", 1, False, "One pair per drawer"),
            ("HDL-AL-160", 1, False, ""),
            ("SCR-8X25", 1, False, ""),
            ("SD-SET-6", 1, True, ""),
        ],
    ),
    (
        "Demo: Wardrobe shutter kit",
        "custom",
        "Demo kit: hinges, handles and a hanging rail for a two-door wardrobe.",
        "",
        [
            ("HNG-SC-FO", 2, False, "Two pairs for two doors"),
            ("HDL-AL-224", 2, False, ""),
            ("WR-RAIL-4", 1, False, ""),
            ("SCR-8X25", 1, False, ""),
        ],
    ),
    (
        "Demo: Door lock fitting kit",
        "diy_repair",
        "Demo kit: replace a bedroom door lock and add a tower bolt.",
        "",
        [
            ("LCK-MOR-SS", 1, False, ""),
            ("TB-8-SS", 1, True, ""),
            ("SD-SET-6", 1, True, ""),
        ],
    ),
]

# "Complete the project" rules: (source category slug, target category slug, label, priority)
RECOMMENDATION_RULES = [
    ("drills", "drill-bits", "Bits for your drill", 10),
    ("plywood", "fevicol", "Adhesives for your boards", 10),
    ("plywood", "hinges-channels-handles", "Hinges, channels and handles", 20),
    ("hinges", "fasteners", "Screws to fit them", 20),
    ("kitchen-baskets", "drawer-channels", "Channels for the drawers", 20),
    ("grinders", "safety", "Protect yourself while cutting", 30),
    ("glass-door-hardware", "sealants", "Seal the glass edges", 30),
]
