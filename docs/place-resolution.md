# Place, neighbourhood and district resolution

This document explains how the `place` and `place_district` parameters are
resolved and why free-text addresses are not accepted. Code:
`app/services/places.py`; data: `app/data/places.json` and
`app/data/neighborhoods.json`.

## Two-layer source

| Layer | Source | Records | Use |
|---|---|---|---|
| Neighbourhood inventory | CKAN `muhtarliklar` (`7d0b7f55-…`) | 1,292 mukhtar offices → **1,219** unique neighbourhoods, 30 districts | Most `place` matches |
| Hand-picked | OpenStreetMap Nominatim | 30 districts + 24 landmarks | District names and non-neighbourhood places such as `Kemeraltı`, `Kültürpark` |

Both layers are **bundled files**; resolution makes no network call.

## Resolution order

1. The name is normalised in a Turkish-aware way (`İ`/`I`, `ş`/`s`, case).
2. A `", izmir"` / `" izmir"` suffix is stripped.
3. **A district label wins over a neighbourhood.** İzmir has a "Konak"
   neighbourhood inside Konak district and a "Karşiyaka" neighbourhood inside
   Torbalı; the district reading wins.
4. A single match is returned as is.
5. Several neighbourhood matches are an **error**: candidates are listed and
   `place_district` is requested. The first match is **never** picked
   silently.

```text
place="Konak"                      -> Konak district
place="Abdi İpekçi"                -> Abdi İpekçi neighbourhood (Karabağlar)
place="Atatürk"                    -> validation_error: occurs in 17 districts
place="Atatürk", place_district="Bornova" -> Atatürk neighbourhood (Bornova)
```

## Why there are no free-text addresses

- İzmir has **no** official machine-readable geocoding endpoint
  (`openapi .../ibb/cbs/adres*` → 404; verified 2026-10-28).
- Making Nominatim the primary geocoder brings usage-policy, caching and
  rate-limit burdens, while the published inventory already covers most İzmir
  queries.
- Reducing a street address to a neighbourhood point would claim a precision
  that does not exist. An explicit error is returned instead.

## Precision

A neighbourhood point is the **average of the mukhtar office points** in that
neighbourhood. It is **not** a neighbourhood boundary, polygon or door
coordinate. Radius queries state this approximation in `warnings`.

## Name normalisation

Published names are UPPERCASE. `str.title()` turns the Turkish `i` into a
combining dot (`U+0307`), so a dedicated `turkish_title` is used:

```text
AŞAĞIŞAKRAN   -> Aşağışakran
ABDİ İPEKÇİ   -> Abdi İpekçi
1.KADRİYE     -> 1.Kadriye
B.HAYRETTİN PAŞA -> B.Hayrettin Paşa
```
