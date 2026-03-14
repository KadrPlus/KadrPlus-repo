#!/usr/bin/env python3
"""
KadrPlus Repository – generator addons.xml i addons.xml.md5
Uruchom po wgraniu nowego ZIPa: python update_repo.py
"""
import hashlib
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_DIR = Path(__file__).parent
ZIPS_DIR = REPO_DIR / "zips"
ADDONS_XML = REPO_DIR / "addons.xml"
ADDONS_MD5 = REPO_DIR / "addons.xml.md5"
REPO_ADDON_XML = REPO_DIR / "addon.xml"


def get_addon_xml_from_zip(zip_path):
    """Wyciąga addon.xml z ZIPa wtyczki."""
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            if name.endswith('addon.xml') and name.count('/') == 1:
                return z.read(name).decode('utf-8')
    return None


def find_latest_zips():
    """Znajduje najnowszy ZIP dla każdej wtyczki."""
    addons = {}
    for addon_dir in ZIPS_DIR.iterdir():
        if not addon_dir.is_dir():
            continue
        zips = sorted(addon_dir.glob("*.zip"), reverse=True)
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
    repo_tree = ET.parse(REPO_ADDON_XML)
    root.append(repo_tree.getroot())

    # Dodaj wszystkie wtyczki ze zips/
    found = find_latest_zips()
    for addon_id, zip_path in found.items():
        xml_content = get_addon_xml_from_zip(zip_path)
        if xml_content is None:
            print(f"  UWAGA: brak addon.xml w {zip_path.name}")
            continue
        addon_elem = ET.fromstring(xml_content)
        version = addon_elem.get('version', '?')
        print(f"  Dodaję: {addon_id} v{version}")
        root.append(addon_elem)

    # Zapisz addons.xml
    ET.indent(root, space="    ")
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")

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
