"""Fictional names used by the sample generator. None of these are real filers."""

from __future__ import annotations

PARTNERSHIP_NAMES: tuple[str, ...] = (
    "SAMPLE Northwind Partners LP",
    "SAMPLE Harborline Capital LP",
    "SAMPLE Redcedar Ventures LP",
    "SAMPLE Glasshouse Equity LP",
    "SAMPLE Brightmile Holdings LP",
    "SAMPLE Copperlane Fund LP",
    "SAMPLE Stoneorchard Partners LP",
    "SAMPLE Fairweather Capital LP",
)

PARTNER_NAMES: tuple[str, ...] = (
    "SAMPLE Avery Quinn",
    "SAMPLE Blake Harlow",
    "SAMPLE Casey Nguyen",
    "SAMPLE Drew Patel",
    "SAMPLE Ellis Okonkwo",
    "SAMPLE Finley Cho",
    "SAMPLE Gray Adelman",
    "SAMPLE Harper Singh",
    "SAMPLE Indigo Brooks",
    "SAMPLE Jules Moreau",
)

STREETS: tuple[str, ...] = (
    "100 Market Street",
    "10 Oak Avenue",
    "250 River Road",
    "18 Cedar Lane",
    "400 Pine Street",
    "77 Lakeview Drive",
)

CITIES: tuple[tuple[str, str, str], ...] = (
    ("Chicago", "IL", "60601"),
    ("Nashville", "TN", "37201"),
    ("Austin", "TX", "78701"),
    ("Denver", "CO", "80202"),
    ("Seattle", "WA", "98101"),
    ("Boston", "MA", "02110"),
    ("Atlanta", "GA", "30303"),
    ("Portland", "OR", "97201"),
)

IRS_CENTERS: tuple[str, ...] = ("Ogden", "Kansas City", "E-file")

ENTITY_TYPES: tuple[str, ...] = (
    "Individual",
    "Corporation",
    "Partnership",
    "S corporation",
    "Trust",
    "LLC",
)

CAPITAL_METHODS: tuple[str, ...] = ("Tax basis", "GAAP", "Section 704(b)", "Other")

TAX_YEARS: tuple[int, ...] = (2022, 2023, 2024)
