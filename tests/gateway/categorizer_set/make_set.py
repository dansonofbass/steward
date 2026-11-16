"""Builds the categorizer's fictional labelled set (spec 6.1, ruling 13): 540 rows across the 26 categories the model
may give (Loan payments, Pets and Cash and ATM joined Oct 28), from invented merchants in bank-statement shapes, and 60 vague rows labelled uncategorized. Deterministic.
No row matches a milestone 1 rule: the model only ever sees rows the rules missed.
Write the file with: uv run python -m tests.gateway.categorizer_set.make_set"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
SEED = 20261021
CITIES = ["OAKHAVEN", "BRINDLEWOOD", "LARKSPUR GLEN", "FENWICK", "MARROW BAY", "ALDERBROOK", "QUILLFIELD"]
STATES = ["CA", "OR", "WA", "NV", "AZ"]
MERCHANTS: dict[str, list[str]] = {
    "groceries": ["GREENLEAF MARKET", "HARVEST BASKET GROCERY", "CORNER PANTRY FOODS", "FRESHFIELD SUPERMARKET",
                  "VALLEY FARM MARKET", "SUNRISE FOODS", "BLUE BARN GROCERS", "PINECONE FOOD CO-OP"],
    "dining": ["MAPLE LEAF CAFE", "RED LANTERN NOODLE HOUSE", "BRICK OVEN PIZZERIA", "TACO VERDE", "HARBOR GRILL",
               "SUNNY SIDE DINER", "GOLDEN WOK KITCHEN", "BEAN AND BARLEY COFFEE"],
    "housing": ["OAKHAVEN PROPERTY MGMT RENT", "BRINDLEWOOD HOA DUES", "LARKSPUR APARTMENTS RENT",
                "PARKVIEW TOWNHOMES HOA", "STONEGATE RENTALS RENT", "WILLOW COURT HOMEOWNERS ASSN"],
    "utilities": ["FENWICK WATER DISTRICT", "BRIGHTLINE ELECTRIC", "VALLEY GAS AND POWER", "CLEARWAVE INTERNET",
                  "METRO WASTE SERVICES", "SKYLINK WIRELESS BILL"],
    "transport": ["QUICKFUEL GAS STATION", "PARKRIGHT PARKING", "CITY TRANSIT FARE", "SPEEDY LUBE OIL CHANGE",
                  "BAYSIDE TOLL ROAD", "AUTOCARE TIRE CENTER"],
    "travel": ["SKYWARD AIRLINES", "HARBORVIEW HOTEL", "COASTLINE INN", "TRAILHEAD LODGE", "JETSTREAM AIRWAYS",
               "SEASIDE RESORT AND SPA", "NORTHSTAR RAIL TICKETS"],
    "health": ["OAKHAVEN FAMILY PHARMACY", "BRIGHT SMILE DENTAL", "VALLEY MEDICAL GROUP", "CLEARVIEW OPTOMETRY",
               "LAKESIDE URGENT CARE", "WELLSPRING PHYSICAL THERAPY"],
    "insurance": ["SHIELDSURE AUTO INSURANCE", "HOMEGUARD INSURANCE PREMIUM", "LIFELINE MUTUAL LIFE INS",
                  "SAFEHARBOR INSURANCE CO", "TRUSTWAY INS PREMIUM"],
    # Invented lenders: the built-in loan rule only knows real ones, so these are left to the model.
    "loan_payments": ["BLUEPEAK AUTO FINANCE PMT", "HARTWELL CAR CREDIT", "SUMMIT STUDENT LENDING",
                      "RIVERSTONE MOTOR ACCEPTANCE", "BRIGHTPATH EDU LOANS PMT", "OAKLINE PERSONAL LENDING"],
    "childcare_education": ["LITTLE SPROUTS DAYCARE", "BRIGHT MINDS TUTORING", "MAPLE HOLLOW PRESCHOOL",
                            "QUILLFIELD STATE UNIVERSITY TUITION", "KIDZONE AFTERSCHOOL CARE"],
    "giving": ["COMMUNITY CHURCH TITHE", "FOOD BANK DONATION", "HOPE SHELTER DONATION", "GRACE FELLOWSHIP GIVING",
               "ANIMAL RESCUE DONATION"],
    "subscriptions": ["STREAMBOX MONTHLY", "TUNEWAVE PREMIUM", "CLOUDVAULT STORAGE SUBSCRIPTION",
                      "NEWSDAILY DIGITAL SUBSCRIPTION", "PIXELPLAY MONTHLY MEMBERSHIP"],
    "shopping": ["MEGAMART GENERAL STORE", "THREADS CLOTHING", "GADGET HUB ELECTRONICS", "BOOKNOOK BOOKSTORE",
                 "SHOEBOX OUTLET", "HOMESTYLE DEPARTMENT STORE"],
    "personal": ["SHEAR STYLE SALON", "GLOW NAIL SPA", "IRONWORKS GYM MEMBERSHIP", "CLEAN FOLD DRY CLEANERS",
                 "BARBER BROTHERS"],
    # Cash without the word ATM, which the built-in rule takes.
    "cash_atm": ["TELLER CASH OUT", "BRANCH COUNTER CASH", "CASHPOINT KIOSK", "CASH MACHINE WD", "COUNTER CASH ORDER"],
    "kids": ["TOYTOWN TOYS", "KIDS KINGDOM CLOTHING", "LITTLE LEAGUE REGISTRATION", "SPLASH SWIM LESSONS",
             "BOUNCE PARTY PLACE"],
    "pets": ["PAWS AND CLAWS PET SUPPLY", "HAPPY TAILS VETERINARY", "FURRY FRIENDS GROOMING", "BARK PARK BOARDING",
             "WHISKERS PET FOOD"],
    "home": ["HAMMER AND NAIL HARDWARE", "GREEN THUMB GARDEN CENTER", "COZY HOME FURNISHINGS",
             "PRO PLUMBING SERVICES", "SPARKLE CLEANING SERVICE", "PEST AWAY EXTERMINATING"],
    "gifts": ["PETAL AND STEM FLORIST", "GIFT GALLERY", "PARTY CARD SHOP", "BLOOMS FLOWER DELIVERY", "KEEPSAKE GIFTS"],
    "entertainment": ["STARLIGHT CINEMAS", "BOWL-O-RAMA LANES", "QUILLFIELD ZOO TICKETS", "ENCORE CONCERT TICKETS",
                      "FUNZONE ARCADE", "MINI GOLF PARADISE"],
    "income": ["NORTHWIND LOGISTICS SALARY", "ACME WIDGETS PAYCHECK", "VALLEY TEACHERS PENSION",
               "HOLLOWAY CORP SALARY DEPOSIT", "STATE RETIREMENT SYSTEM BENEFIT"],
    "business_income": ["CLIENT INVOICE PAYMENT BLUEPEAK", "CONSULTING FEE HARTWELL CO", "FREELANCE PROJECT PAYMENT",
                        "INVOICE PAID BRIGHTWORKS STUDIO"],
    "business_expense": ["COWORK SPACE MONTHLY", "OFFICE SUPPLY DEPOT", "BIZCARDS PRINTING", "DOMAIN HOSTING ANNUAL",
                         "PROFESSIONAL ASSOC DUES"],
    "taxes": ["COUNTY PROPERTY TAX", "STATE TAX PAYMENT", "CITY PROPERTY TAX COLLECTOR", "ESTIMATED TAX PAYMENT"],
    "fees": ["MONTHLY SERVICE FEE", "OVERDRAFT FEE", "WIRE TRANSFER FEE", "LATE PAYMENT FEE", "FOREIGN TRANSACTION FEE"],
    "interest": ["DIVIDEND EARNED", "SAVINGS DIVIDEND", "APY EARNED", "CD DIVIDEND PAID"],
}
SHAPES = ["{name}", "POS {name} {store}", "SQ *{name}", "{name} #{store} {city} {st}", "DEBIT CARD PURCHASE {name}",
          "TST* {name}", "{name} {city} {st}", "PP*{name}", "ACH {name} PPD"]
INCOME_SHAPES = ["{name}", "ACH CREDIT {name}", "{name} DEPOSIT", "DIRECT CREDIT {name}"]
VAGUE = ["CHECK {store}", "POS PURCHASE", "ACH DEBIT WEB", "DEBIT CARD PURCHASE", "MOBILE DEPOSIT", "WEB DEBIT",
         "ONLINE PAYMENT", "MISC DEBIT", "PURCHASE AUTHORIZED ON {mm}/{dd}", "REF {store} DEBIT", "WITHDRAWAL",
         "DEPOSIT"]
MONEY_IN = {"income", "business_income", "interest"}
RANGES = {"housing": (120_000, 320_000), "income": (180_000, 650_000), "business_income": (50_000, 400_000),
          "travel": (8_000, 90_000), "taxes": (20_000, 400_000), "fees": (300, 3_900), "interest": (50, 9_000),
          "insurance": (6_000, 40_000), "childcare_education": (5_000, 150_000), "loan_payments": (15_000, 90_000),
          "cash_atm": (2_000, 40_000)}


def build() -> list[dict]:
    rnd = random.Random(SEED)
    cats = list(MERCHANTS)
    rows = []
    for i in range(540):
        cat = cats[i % len(cats)]
        shape = rnd.choice(INCOME_SHAPES if cat in MONEY_IN else SHAPES)
        text = shape.format(name=rnd.choice(MERCHANTS[cat]), store=rnd.randint(100, 9999),
                            city=rnd.choice(CITIES), st=rnd.choice(STATES))
        lo, hi = RANGES.get(cat, (500, 25_000))
        cents = rnd.randint(lo, hi)
        rows.append({"id": f"c{i + 1:03d}", "description": text,
                     "amount_cents": cents if cat in MONEY_IN else -cents, "category": cat})
    for i in range(60):
        text = rnd.choice(VAGUE).format(store=rnd.randint(1000, 9999), mm=rnd.randint(1, 12), dd=rnd.randint(1, 28))
        cents = rnd.randint(500, 60_000)
        rows.append({"id": f"v{i + 1:03d}", "description": text,
                     "amount_cents": cents if "DEPOSIT" in text else -cents, "category": "uncategorized"})
    rnd.shuffle(rows)
    return rows


def write() -> None:
    with (HERE / "set.jsonl").open("w") as f:
        for r in build():
            f.write(json.dumps(r, sort_keys=True) + "\n")


if __name__ == "__main__":
    write()
