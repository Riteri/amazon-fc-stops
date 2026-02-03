# Amazon FC - przystanki autobusowe (scraper -> JSON)

**TL;DR:** Projekt zbiera publiczne informacje o przystankach i trasach autobusowych dla magazynów Amazon (FC), zapisuje je do `data/stops.json` i publikuje przez GitHub Pages. Front (WordPress) pobiera JSON i rysuje najbliższe przystanki na mapie. Aktualizacje odbywają się automatycznie przez GitHub Actions.

---

## Źródła danych (serwisy PARSOWANE)

Projekt obsługuje **dwa** typy źródeł:

1) **Nowy portal PDF** (główne źródło, jeśli dostępne):
   - https://transport-fc.pl/employee-transport.html

2) **Dotychczasowe strony transport-fc.eu** (fallback / uzupełnienie):

- **WRO1–WRO4 (wspólny rozkład):** https://wro.transport-fc.eu/rozklady-jazdy/
- **WRO5:** https://wro5.transport-fc.eu/rozklady-jazdy/
- **LCJ2:** https://lcj2.transport-fc.eu/
- **LCJ3:** https://lcj3.transport-fc.eu/
- **LCJ4:** https://lcj4.transport-fc.eu/
- **Pozostałe przykładowe subdomeny:**  
  https://szz1.transport-fc.eu/, https://poz1.transport-fc.eu/, https://poz2.transport-fc.eu/,  
  https://ktw1.transport-fc.eu/, https://ktw3.transport-fc.eu/, https://ktw5.transport-fc.eu/

> Pełna lista aktualnie obsługiwanych subdomen jest w tablicy `FC_SUBS` w pliku `scraper/scrape_transport_fc.py`. Parser HTML filtruje podstrony zawierające linki do **OpenStreetMap** i z nich wyciąga nazwy przystanków oraz współrzędne.

---

## Live JSON (GitHub Pages)

- **Aktualne dane:** `data/stops.json`  
  https://riteri.github.io/amazon-fc-stops/data/stops.json

- **Raport różnic:** `data/changes.json`  
  https://riteri.github.io/amazon-fc-stops/data/changes.json

> Jeśli forkujesz repozytorium — zmień `riteri/amazon-fc-stops` na swoją nazwę użytkownika/nazwę repo i włącz **GitHub Pages** (gałąź `main`, folder `/`).

---

## Jak to działa (architektura)

1. **GitHub Actions** uruchamia workflow wg harmonogramu (cron w **UTC**).  
2. Skrypt **Python** (`scraper/scrape_transport_fc.py`) najpierw parsuje PDF-y z `transport-fc.pl`, a jeśli są dostępne — buduje listy przystanków z treści PDF.  
3. Jeśli PDF-y nie dostarczają współrzędnych:
   - próbuje dopasować do poprzednich przystanków z `data/stops.json`,  
   - a następnie (opcjonalnie) używa geokodera Nominatim i zapisuje wynik do cache.  
4. Dodatkowo (fallback) parsowane są strony `*.transport-fc.eu` z linkami OSM.  
5. Generowane są pliki:  
   - `data/stops.json` – pełna lista przystanków,  
   - `data/changes.json` – różnice względem poprzedniego przebiegu.  
6. Zmiany są **commitowane** do gałęzi `main`.  
7. **GitHub Pages** udostępnia pliki publicznie (URL powyżej).

---

## Konfiguracja i uruchomienie lokalne

```bash
python scraper/scrape_transport_fc.py
```

### Zmienne środowiskowe

- `GEOCODE_ENABLED=0` – wyłącza geokodowanie (przydatne offline).  
- `GEOCODE_DELAY_SEC=1.1` – opóźnienie między zapytaniami do Nominatim.  
- `REQUEST_DELAY_SEC=0.7` – opóźnienie między zapytaniami HTTP do stron źródłowych.  
- `CRAWLER_UA` – własny User-Agent do requestów.  

### Cache geokodowania

Jeśli geokodowanie jest włączone, wyniki zapisywane są do:

```
data/geocode_cache.json
```

Cache pozwala uniknąć ponownego geokodowania tych samych nazw przystanków.

### Uwaga na strefę czasu
- Cron w GitHub Actions jest **zawsze w UTC**.  
- Polska: **CEST (UTC+2)** latem, **CET (UTC+1)** zimą.  
- Przykład harmonogramu „dwa razy dziennie”: `7 */12 * * *` (00:07 i 12:07 UTC).
