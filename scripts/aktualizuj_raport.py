#!/usr/bin/env python3
"""
Skrypt aktualizacji raportu przetargowego.
Uruchamiany przez GitHub Actions co tydzien.
Pobiera dane z publicznego API BZP (ezamowienia.gov.pl).
"""

import requests
import json, re, sys, datetime, shutil, time, os
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).parent.parent
HTML_FILE = ROOT / "index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

# Kody CPV dla systemow eventowych i IT
CPV_KODY = [
    "72212000",  # oprogramowanie aplikacji
    "72416000",  # dostawcy uslug aplikacyjnych
    "79952000",  # uslugi w zakresie organizacji imprez
    "48000000",  # pakiety oprogramowania
    "72222300",  # uslugi IT
]

SLOWA_KLUCZOWE = [
    "event", "impreza", "akredytacja", "ticketing", "konferencja",
    "aplikacja mobilna", "rejestracja uczestnik", "platforma",
    "bilety", "zarządzanie imprez", "system obsługi",
]

def pobierz_bzp_api(fraza: str, strona: int = 0) -> list:
    """Pobiera ogłoszenia z publicznego API BZP."""
    # Oficjalny publiczny endpoint BZP - nie wymaga autoryzacji
    url = "https://ezamowienia.gov.pl/mo-client-board/bzp/api/search"
    params = {
        "searchPhrase": fraza,
        "pageSize": 20,
        "pageOffset": strona * 20,
        "sortingRule": "PUBLICATION_DATE",
        "sortingOrder": "DESC",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            items = data.get("notices") or data.get("items") or data.get("results") or []
            if items:
                print(f"      API BZP: {len(items)} wynikow")
                return items
    except Exception as e:
        pass

    # Fallback - drugi endpoint
    url2 = "https://ezamowienia.gov.pl/mo-client-board/api/v1/notice/search"
    try:
        r = requests.post(url2, json={
            "searchPhrase": fraza,
            "pageSize": 20,
            "pageOffset": 0,
        }, headers={**HEADERS, "Content-Type": "application/json"}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            items = data.get("notices") or data.get("content") or []
            if items:
                print(f"      API BZP v2: {len(items)} wynikow")
                return items
    except Exception as e:
        pass

    return []


def pobierz_bzp_cpv(cpv: str) -> list:
    """Pobiera ogłoszenia z BZP po kodzie CPV."""
    url = "https://ezamowienia.gov.pl/mo-client-board/bzp/api/search"
    params = {
        "cpvCode": cpv,
        "pageSize": 20,
        "pageOffset": 0,
        "sortingRule": "PUBLICATION_DATE",
        "sortingOrder": "DESC",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data.get("notices") or data.get("items") or []
    except:
        pass
    return []


def pobierz_bzp_scraping(fraza: str) -> list:
    """Scraping wyszukiwarki BZP jako fallback."""
    from bs4 import BeautifulSoup
    url = f"https://ezamowienia.gov.pl/mo-client-board/bzp/list?searchPhrase={quote_plus(fraza)}"
    wyniki = []
    try:
        headers_html = {**HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
        r = requests.get(url, headers=headers_html, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Szukaj ogloszen w tabeli BZP
        for row in soup.select("tr, .notice-row, [class*='notice'], [class*='ogloszenie']"):
            a = row.select_one("a[href*='notice'], a[href*='ogloszenie']")
            if not a:
                continue
            tytul = a.get_text(strip=True)
            if len(tytul) < 20:
                continue
            href = a.get("href", "")
            link = f"https://ezamowienia.gov.pl{href}" if href.startswith("/") else href
            tekst = row.get_text(" ", strip=True)
            termin = "-"
            dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
            if dm:
                termin = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
            wyniki.append({
                "tytul": tytul[:180],
                "zamawiajacy": "",
                "termin": termin,
                "nr": "",
                "link": link,
                "woj": "Polska",
                "zrodlo": "BZP",
            })
            if len(wyniki) >= 8:
                break
    except Exception as e:
        print(f"      scraping BZP: {e}")
    return wyniki


def mapuj_api(item: dict, idx: int) -> dict:
    """Mapuje rekord z API BZP na format raportu."""
    # Rozne nazwy pol w roznych wersjach API
    tytul = (
        item.get("procurementName") or item.get("noticeName") or
        item.get("title") or item.get("name") or "Brak tytulu"
    )[:180]

    zam = (
        item.get("buyerName") or item.get("contractingAuthorityName") or
        item.get("organizationName") or item.get("buyer") or "Zamawiajacy publiczny"
    )

    termin = (
        item.get("submissionDeadline") or item.get("offerDeadline") or
        item.get("deadline") or "-"
    )
    if termin and termin != "-":
        termin = termin[:10]  # tylko data YYYY-MM-DD

    nr = (
        item.get("noticeNumber") or item.get("publicationNumber") or
        item.get("referenceNumber") or f"BZP-{idx:06d}"
    )

    # Link bezposredni do ogloszenia
    notice_id = item.get("noticeId") or item.get("id") or ""
    link = item.get("url") or item.get("link") or ""
    if not link and notice_id:
        link = f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice/{notice_id}"
    if not link:
        link = f"https://ezamowienia.gov.pl/mo-client-board/bzp/list?searchPhrase={quote_plus(tytul[:50])}"

    t = tytul.lower()
    tagi = []
    for slowo, tag in [
        ("akredytacj","akredytacja"), ("bilet","ticketing"), ("mobiln","aplikacja mobilna"),
        ("rfid","RFID"), ("stadion","stadion"), ("konferencj","konferencja"),
        ("festiwal","festiwal"), ("imprez","impreza"), ("rejestr","rejestracja"),
        ("saas","SaaS"), ("qr","QR kod"),
    ]:
        if slowo in t:
            tagi.append(tag)
        if len(tagi) >= 3:
            break
    if not tagi:
        tagi = ["system IT", "zamowienie publiczne"]

    return {
        "id": f"PT{idx:03d}",
        "title": tytul,
        "zam": zam,
        "typ": ustal_typ(zam),
        "kat": ustal_kat(tytul),
        "status": ustal_status(termin),
        "wartosc": formatuj_wartosc(
            item.get("estimatedValue") or item.get("contractValue") or ""
        ),
        "termin": termin,
        "nr": nr,
        "link": link,
        "zrodlo": "BZP",
        "woj": item.get("region") or item.get("voivodeship") or "Polska",
        "opis": tytul,
        "tagi": tagi[:4],
    }


def mapuj_scraping(item: dict, idx: int) -> dict:
    """Mapuje rekord ze scrapingu na format raportu."""
    tytul = item.get("tytul", "Brak tytulu")[:180]
    t = tytul.lower()
    tagi = []
    for slowo, tag in [
        ("akredytacj","akredytacja"), ("bilet","ticketing"), ("mobiln","aplikacja mobilna"),
        ("stadion","stadion"), ("konferencj","konferencja"), ("festiwal","festiwal"),
        ("imprez","impreza"), ("rejestr","rejestracja"),
    ]:
        if slowo in t:
            tagi.append(tag)
        if len(tagi) >= 3:
            break
    if not tagi:
        tagi = ["system IT", "zamowienie publiczne"]

    zam = item.get("zamawiajacy", "") or "Zamawiajacy publiczny"
    termin = item.get("termin", "-")
    nr = item.get("nr") or f"BZP-{idx:06d}"
    link = item.get("link") or f"https://ezamowienia.gov.pl/mo-client-board/bzp/list?searchPhrase={quote_plus(tytul[:50])}"

    return {
        "id": f"PT{idx:03d}",
        "title": tytul,
        "zam": zam,
        "typ": ustal_typ(zam),
        "kat": ustal_kat(tytul),
        "status": ustal_status(termin),
        "wartosc": "Nie podano",
        "termin": termin,
        "nr": nr,
        "link": link,
        "zrodlo": item.get("zrodlo", "BZP"),
        "woj": item.get("woj", "Polska"),
        "opis": tytul,
        "tagi": tagi[:4],
    }


def ustal_typ(z: str) -> str:
    n = z.upper()
    for s in ["PKP","PKO","PGE","KGHM","ORLEN","PERN","ENEA","TAURON","PZU","BGK","LOTOS","PGNIG"]:
        if s in n: return "SSP"
    for c in ["FILHARMON","OPERA","TEATR","MUZEUM","GALERIA","PKOL","KULTURY","FUNDACJA","OLIMP","MCK"]:
        if c in n: return "CULT"
    return "MUN"


def ustal_kat(t: str) -> str:
    t = t.lower()
    if any(w in t for w in ["akredytacja","rejestracja uczest"]): return "acc"
    if any(w in t for w in ["mobiln","ticketing","bilet","ios","android"]): return "app"
    return "plat"


def ustal_status(termin: str) -> str:
    if termin and termin != "-":
        try:
            if datetime.datetime.strptime(termin[:10], "%Y-%m-%d") < datetime.datetime.now():
                return "eval"
        except:
            pass
    return "new"


def formatuj_wartosc(v) -> str:
    if not v:
        return "Nie podano"
    try:
        n = float(str(v).replace(",", ".").replace(" ", ""))
        return f"{n/1_000_000:.1f} mln PLN" if n >= 1_000_000 else f"{n:,.0f} PLN".replace(",", " ")
    except:
        return str(v) if v else "Nie podano"


SLOWA_EVENT = [
    "event","impreza","imprez","konferencja","konferencj","kongres","festiwal",
    "stadion","akredytacja","akredytacj","bilet","ticketing","aplikacja","mobilna",
    "rejestracja","uczestnik","widownia","hala","arena","platforma","widowisk",
]

def ocen(item: dict) -> int:
    tekst = (item.get("tytul","") + " " + item.get("zamawiajacy","")).lower()
    return min(sum(15 for w in SLOWA_EVENT if w in tekst), 100)


def deduplikuj(lista: list) -> list:
    seen, wynik = set(), []
    for x in lista:
        k = x.get("tytul","")[:60].lower().strip()
        if k and len(k) > 10 and k not in seen:
            seen.add(k)
            wynik.append(x)
    return wynik


def aktualizuj_html(przetargi: list):
    if not HTML_FILE.exists():
        print(f"BLAD: brak {HTML_FILE}")
        sys.exit(1)
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    nowe = json.dumps(przetargi, ensure_ascii=False, indent=2)
    nowy = re.sub(r"const DATA = \[[\s\S]*?\];", f"const DATA = {nowe};", html)
    now = datetime.datetime.now()
    nowy = re.sub(r"Tydzie[ń\u0144n] \d+ / \d+",
                  f"Tydzień {now.isocalendar()[1]} / {now.year}", nowy)
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as f:
            f.write(f"DATA_AKTUALIZACJI={now.strftime('%d.%m.%Y')}\n")
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(nowy)
    print(f"  ✅ Zaktualizowano: {HTML_FILE.name}")
    print(f"  📊 Przetargow: {len(przetargi)}")
    print(f"  📅 Tydzien: {now.isocalendar()[1]}/{now.year}")


def main():
    print("=" * 55)
    print("  AKTUALIZACJA RAPORTU PRZETARGOWEGO")
    print(f"  {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')} UTC")
    print("=" * 55)

    wszystkie_api = []
    wszystkie_scraping = []

    # === KROK 1: API BZP po frazach ===
    print("\n📡 Krok 1: API BZP — frazy kluczowe")
    for fraza in SLOWA_KLUCZOWE:
        print(f"  '{fraza}'", end=" ", flush=True)
        wyniki = pobierz_bzp_api(fraza)
        if wyniki:
            wszystkie_api.extend(wyniki)
            print(f"→ {len(wyniki)}")
        else:
            print("→ 0")
        time.sleep(0.5)

    # === KROK 2: API BZP po CPV ===
    print("\n📡 Krok 2: API BZP — kody CPV")
    for cpv in CPV_KODY:
        print(f"  CPV {cpv}", end=" ", flush=True)
        wyniki = pobierz_bzp_cpv(cpv)
        if wyniki:
            wszystkie_api.extend(wyniki)
            print(f"→ {len(wyniki)}")
        else:
            print("→ 0")
        time.sleep(0.5)

    print(f"\n  Z API: {len(wszystkie_api)} rekordow")

    # === KROK 3: Scraping BZP jako fallback ===
    if len(wszystkie_api) < 5:
        print("\n📡 Krok 3: Scraping BZP (fallback)")
        try:
            from bs4 import BeautifulSoup
            for fraza in ["aplikacja mobilna event", "system akredytacji", "platforma eventowa"]:
                print(f"  '{fraza}'", end=" ", flush=True)
                w = pobierz_bzp_scraping(fraza)
                wszystkie_scraping.extend(w)
                print(f"→ {len(w)}")
                time.sleep(1)
        except ImportError:
            print("  bs4 niedostepne")

    # === MAPOWANIE ===
    przetargi = []

    if wszystkie_api:
        # Filtruj trafne z API
        trafne = [x for x in wszystkie_api if any(
            w in (x.get("procurementName","") + x.get("noticeName","") + x.get("title","")).lower()
            for w in SLOWA_EVENT
        )]
        print(f"\n  Trafnych z API: {len(trafne)} / {len(wszystkie_api)}")

        if not trafne:
            trafne = wszystkie_api[:20]

        # Deduplikuj po tytule
        seen = set()
        unikalne = []
        for x in trafne:
            k = (x.get("procurementName") or x.get("title",""))[:60].lower()
            if k and k not in seen:
                seen.add(k)
                unikalne.append(x)

        przetargi = [mapuj_api(x, i+1) for i, x in enumerate(unikalne[:20])]

    elif wszystkie_scraping:
        trafne = deduplikuj([x for x in wszystkie_scraping if len(x.get("tytul","")) > 15])
        przetargi = [mapuj_scraping(x, i+1) for i, x in enumerate(trafne)]

    print(f"\n  Przetargow do raportu: {len(przetargi)}")

    # Pokaz pierwsze 3
    for p in przetargi[:3]:
        print(f"  → {p['title'][:70]}")
        print(f"     Link: {p['link'][:80]}")

    if not przetargi:
        print("\n  ⚠ Brak wynikow — API BZP niedostepne.")
        print("  Raport nie zostanie zmieniony.")
        sys.exit(0)

    aktualizuj_html(przetargi)
    n = sum(1 for p in przetargi if p["status"] == "new")
    print(f"\n  GOTOWE — {len(przetargi)} przetargow ({n} nowych)")


if __name__ == "__main__":
    main()
