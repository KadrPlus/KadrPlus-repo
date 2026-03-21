#!/usr/bin/env python3
"""
KadrPlus Repository – generator addons.xml i addons.xml.md5
Uruchom po wgraniu nowego ZIPa: python update_repo.py
"""
import hashlib
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_DIR = Path(__file__).parent
ZIPS_DIR = REPO_DIR / "zips"
ADDONS_XML = REPO_DIR / "addons.xml"
ADDONS_MD5 = REPO_DIR / "addons.xml.md5"
REPO_ADDON_XML = REPO_DIR / "addon.xml"


def version_key(zip_path):
    """Sortowanie wg numeru wersji (nie alfabetycznie)."""
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', zip_path.name)
    if m:
        return tuple(int(x) for x in m.groups())
    return (0, 0, 0)


def sanitize_xml(xml_content):
    """Zamienia niedozwolone HTML encje na ich odpowiedniki UTF-8."""
    html_entities = {
        '&ouml;': 'ö', '&auml;': 'ä', '&uuml;': 'ü',
        '&Ouml;': 'Ö', '&Auml;': 'Ä', '&Uuml;': 'Ü',
        '&szlig;': 'ß', '&nbsp;': ' ', '&eacute;': 'é',
        '&egrave;': 'è', '&oacute;': 'ó', '&oacute;': 'ó',
    }
    for entity, char in html_entities.items():
        xml_content = xml_content.replace(entity, char)
    # Usuń wszelkie pozostałe &nazwa; które nie są poprawnymi XML encjami
    xml_content = re.sub(
        r'&(?!amp;|lt;|gt;|apos;|quot;|#\d+;|#x[0-9a-fA-F]+;)([a-zA-Z][a-zA-Z0-9]*;)',
        r'\1', xml_content
    )
    return xml_content


def get_addon_xml_from_zip(zip_path):
    """Wyciąga addon.xml z ZIPa wtyczki."""
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            if name.endswith('addon.xml') and name.count('/') == 1:
                return z.read(name).decode('utf-8')
    return None


def find_latest_zips():
    """Znajduje najnowszy ZIP dla każdej wtyczki (sortowanie wg wersji)."""
    addons = {}
    for addon_dir in ZIPS_DIR.iterdir():
        if not addon_dir.is_dir():
            continue
        zips = sorted(addon_dir.glob("*.zip"), key=version_key, reverse=True)
        if zips:
            addons[addon_dir.name] = zips[0]
            print(f"  Znaleziono: {zips[0].name}")
            if len(zips) > 1:
                print(f"  (pomijam starsze: {', '.join(z.name for z in zips[1:])})")
    return addons


def build_addons_xml():
    print("\n=== Generowanie addons.xml ===\n")

    root = ET.Element("addons")

    # Dodaj sam repo jako addon
    repo_xml = sanitize_xml(REPO_ADDON_XML.read_text(encoding='utf-8'))
    root.append(ET.fromstring(repo_xml))

    # Dodaj wszystkie wtyczki ze zips/
    found = find_latest_zips()
    for addon_id, zip_path in found.items():
        xml_content = get_addon_xml_from_zip(zip_path)
        if xml_content is None:
            print(f"  UWAGA: brak addon.xml w {zip_path.name}")
            continue
        try:
            xml_content = sanitize_xml(xml_content)
            addon_elem = ET.fromstring(xml_content)
        except ET.ParseError as e:
            print(f"  BŁĄD parsowania {zip_path.name}: {e}")
            continue
        version = addon_elem.get('version', '?')
        print(f"  Dodaję: {addon_id} v{version}")
        root.append(addon_elem)

    # Zapisz addons.xml
    ET.indent(root, space="    ")
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
    ADDONS_XML.write_text(xml_str, encoding='utf-8')
    print(f"\n  Zapisano: {ADDONS_XML}")

    # Wygeneruj MD5
    md5 = hashlib.md5(xml_str.encode('utf-8')).hexdigest()
    ADDONS_MD5.write_text(md5)
    print(f"  MD5: {md5}")
    print(f"  Zapisano: {ADDONS_MD5}")

    print("\n=== Gotowe! Zrób git commit + push ===\n")


if __name__ == "__main__":
    build_addons_xml()
