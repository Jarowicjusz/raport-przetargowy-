#!/usr/bin/env python3
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

CPV_KODY = ["72212000","72416000","79952000","48000000","72222300"]

SLOWA_KLUCZOWE = [
    "event","impreza","akredytacja","ticketing","konferencja",
    "aplikacja mobilna","rejestracja uczestnik","bilety",
]

SLOWA_EVENT = [
    "event","impreza","imprez","konferencja","konferencj","festiwal",
    "stadion","akredytacja","akredytacj","bilet","ticketing","aplikacja",
    "mobilna","rejestracja","uczestnik","widownia","hala","arena","platforma",
]

def pobierz(fraza, cpv=None):
    url = "https://ezamowienia.gov.pl/mo-client-board/bzp/api/search"
    params = {"pageSize":20,"pageOffset":0,"sortingRule":"PUBLICATION_DATE","sortingOrder":"DESC"}
    if cpv:
        params["cpvCode"] = cpv
    else:
        params["searchPhrase"] = fraza
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            d = r.json()
            return d.get("notices") or d.get("items") or d.get("results") or []
    except:
        pass
    return []

def ustal_typ(z):
    n = z.upper()
    for s in ["PKP","PKO","PGE","KGHM","ORLEN","PERN","ENEA","TAURON","PZU","BGK","LOTOS","PGNIG"]:
        if s in n: return "SSP"
    for c in ["FILHARMON","OPERA","TEATR","MUZEUM","GALERIA","PKOL","KULTURY","FUNDACJA","OLIMP","MCK"]:
        if c in n: return "CULT"
    return "MUN"

def ustal_kat(t):
    t = t.lower()
    if any(w in t for w in ["akredytacja","rejestracja uczest"]): return "acc"
    if any(w in t for w in ["mobiln","ticketing","bilet","ios","android"]): return "app"
    return "plat"

def ustal_status(termin):
    if termin and termin != "-":
        try:
            if datetime.datetime.strptime(termin[:10],"%Y-%m-%d") < datetime.datetime.now():
                return "eval"
        except: pass
    return "new"

def formatuj_wartosc(v):
    if not v: return "Nie podano"
    try:
        n = float(str(v).replace(",",".").replace(" ",""))
        return f"{n/1_000_000:.1f} mln PLN" if n>=1_000_000 else f"{n:,.0f} PLN".replace(",","")
    except: return str(v) if v else "Nie podano"

def mapuj(item, idx):
    tytul = (item.get("procurementName") or item.get("noticeName") or item.get("title") or "Brak")[:180]
    zam = item.get("buyerName") or item.get("contractingAuthorityName") or "Zamawiajacy publiczny"
    termin = (item.get("submissionDeadline") or item.get("offerDeadline") or "-")
    if termin != "-": termin = termin[:10]
    nr = item.get("noticeNumber") or item.get("publicationNumber") or f"BZP-{idx:06d}"
    notice_id = item.get("noticeId") or item.get("id") or ""
    link = item.get("url") or ""
    if not link and notice_id:
        link = f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice/{notice_id}"
    if not link:
        link = f"https://ezamowienia.gov.pl/mo-client-board/bzp/list?searchPhrase={quote_plus(tytul[:50])}"
    t = tytul.lower()
    tagi = []
    for s,g in [("akredytacj","akredytacja"),("bilet","ticketing"),("mobiln","aplikacja mobilna"),
                ("stadion","stadion"),("konferencj","konferencja"),("festiwal","festiwal"),
                ("imprez","impreza"),("rejestr","rejestracja")]:
        if s in t: tagi.append(g)
        if len(tagi)>=3: break
    if not tagi: tagi=["system IT","zamowienie publiczne"]
    return {
        "id":f"PT{idx:03d}","title":tytul,"zam":zam,
        "typ":ustal_typ(zam),"kat":ustal_kat(tytul),"status":ustal_status(termin),
        "wartosc":formatuj_wartosc(item.get("estimatedValue") or item.get("contractValue") or ""),
        "termin":termin,"nr":nr,"link":link,"zrodlo":"BZP",
        "woj":item.get("region") or item.get("voivodeship") or "Polska",
        "opis":tytul,"tagi":tagi[:4],
    }

def aktualizuj_html(przetargi):
    with open(HTML_FILE,"r",encoding="utf-8") as f: html=f.read()
    nowe = json.dumps(przetargi,ensure_ascii=False,indent=2)
    nowy = re.sub(r"const DATA = \[[\s\S]*?\];",f"const DATA = {nowe};",html)
    now = datetime.datetime.now()
    nowy = re.sub(r"Tydzie[ń\u0144n] \d+ / \d+",f"Tydzień {now.isocalendar()[1]} / {now.year}",nowy)
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"],"a") as f:
            f.write(f"DATA_AKTUALIZACJI={now.strftime('%d.%m.%Y')}\n")
    with open(HTML_FILE,"w",encoding="utf-8") as f: f.write(nowy)
    print(f"  Zaktualizowano: {len(przetargi)} przetargow")

def main():
    print("="*50)
    print(f"  AKTUALIZACJA RAPORTU {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')} UTC")
    print("="*50)
    wszystkie = []
    print("\nKrok 1: frazy kluczowe")
    for fraza in SLOWA_KLUCZOWE:
        w = pobierz(fraza)
        print(f"  '{fraza}' -> {len(w)}")
        wszystkie.extend(w)
        time.sleep(0.5)
    print("\nKrok 2: kody CPV")
    for cpv in CPV_KODY:
        w = pobierz(None, cpv)
        print(f"  CPV {cpv} -> {len(w)}")
        wszystkie.extend(w)
        time.sleep(0.5)
    print(f"\nZebrano: {len(wszystkie)}")
    trafne = [x for x in wszystkie if any(
        s in (x.get("procurementName","") + x.get("noticeName","") + x.get("title","")).lower()
        for s in SLOWA_EVENT)]
    print(f"Trafnych: {len(trafne)}")
    if not trafne:
        trafne = wszystkie[:20]
    seen, unikalne = set(), []
    for x in trafne:
        k = (x.get("procurementName") or x.get("title",""))[:60].lower()
        if k and k not in seen:
            seen.add(k); unikalne.append(x)
    przetargi = [mapuj(x,i+1) for i,x in enumerate(unikalne[:20])]
    for p in przetargi[:3]:
        print(f"  -> {p['title'][:60]}")
        print(f"     {p['link'][:80]}")
    if not przetargi:
        print("Brak wynikow."); sys.exit(0)
    aktualizuj_html(przetargi)
    print(f"\nGOTOWE — {len(przetargi)} przetargow")

if __name__ == "__main__":
    main()
