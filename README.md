# KadrPlus Repository

Oficjalne repozytorium Kodi dla wtyczki **Kadr+**.

## Instalacja w Kodi

1. Włącz nieznane źródła: **Ustawienia → System → Dodatki → Nieznane źródła**
2. Dodaj źródło pliku: **Menedżer plików → Dodaj źródło**
   ```
   https://kadrplus.github.io/KadrPlus-repo/
   ```
   Nazwij je np. `KadrPlus`
3. Zainstaluj repo: **Dodatki → Zainstaluj z pliku ZIP → KadrPlus → addon.xml** (lub plik ZIP repo)
4. Zainstaluj wtyczkę: **Dodatki → Zainstaluj z repozytorium → KadrPlus Repository → Dodatki wideo → Kadr+**

Kodi będzie odtąd automatycznie powiadamiał o nowych wersjach Kadr+.

---

## Dla autora – aktualizacja repozytorium

Po wydaniu nowej wersji Kadr+:

```bash
# 1. Wrzuć nowy ZIP do zips/plugin.video.kadrplus/
# 2. Wygeneruj addons.xml
python update_repo.py
# 3. Wyślij na GitHub
git add .
git commit -m "Kadr+ vX.XX"
git push
```

---

## Wsparcie

☕ Ko-fi: https://ko-fi.com/J3J41VKK95
