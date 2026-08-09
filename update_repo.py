#!/usr/bin/env python3
"""
Generator repozytorium Kodi dla Kadr+.

Najczęstsze użycie:
    python3 update_repo.py
    python3 update_repo.py /sciezka/plugin.video.kadrplus2-2.0.52.zip
    python3 update_repo.py --check

Podanie ZIP-a jako argumentu:
  * sprawdza integralność paczki oraz zgodność ID, wersji i nazwy,
  * kopiuje ją do zips/<addon_id>/,
  * kopiuje grafiki zadeklarowane w <assets>,
  * synchronizuje główny addon.xml repozytorium z najnowszym ZIP-em
    repository.kadrplus znalezionym w zips/,
  * generuje addons.xml i addons.xml.md5.

Dzięki temu po dodaniu nowej paczki repozytorium, np.
repository.kadrplus-1.0.3.zip, nie trzeba osobno pamiętać o ręcznej
podmianie głównego addon.xml.

Skrypt nie wykonuje git commit ani git push.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET


REPO_DIR = Path(__file__).resolve().parent
ZIPS_DIR = REPO_DIR / "zips"
ADDONS_XML = REPO_DIR / "addons.xml"
ADDONS_MD5 = REPO_DIR / "addons.xml.md5"
REPO_ADDON_XML = REPO_DIR / "addon.xml"

ADDON_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
VALID_XML_ENTITIES_RE = re.compile(
    r"&(?!amp;|lt;|gt;|apos;|quot;|#\d+;|#x[0-9a-fA-F]+;)"
    r"([a-zA-Z][a-zA-Z0-9]*;)"
)
HTML_ENTITIES = {
    "&ouml;": "ö",
    "&auml;": "ä",
    "&uuml;": "ü",
    "&Ouml;": "Ö",
    "&Auml;": "Ä",
    "&Uuml;": "Ü",
    "&szlig;": "ß",
    "&nbsp;": " ",
    "&eacute;": "é",
    "&egrave;": "è",
    "&oacute;": "ó",
}


class RepoError(RuntimeError):
    """Błąd, który uniemożliwia bezpieczne wygenerowanie repozytorium."""


@dataclass(frozen=True)
class AddonArchive:
    path: Path
    addon_id: str
    version: str
    root_dir: str
    manifest_text: str
    manifest: ET.Element

    @property
    def canonical_name(self) -> str:
        return f"{self.addon_id}-{self.version}.zip"


def sanitize_xml(xml_content: str) -> str:
    """Zamienia encje HTML, które nie są prawidłowymi encjami XML."""
    for entity, char in HTML_ENTITIES.items():
        xml_content = xml_content.replace(entity, char)
    return VALID_XML_ENTITIES_RE.sub(r"\1", xml_content)


def parse_manifest(xml_content: str, source: str) -> ET.Element:
    try:
        root = ET.fromstring(sanitize_xml(xml_content))
    except ET.ParseError as exc:
        raise RepoError(f"Nieprawidłowy XML w {source}: {exc}") from exc

    if root.tag != "addon":
        raise RepoError(f"{source}: element główny musi mieć nazwę <addon>.")

    addon_id = (root.get("id") or "").strip()
    version = (root.get("version") or "").strip()
    if not ADDON_ID_RE.fullmatch(addon_id):
        raise RepoError(f"{source}: nieprawidłowe ID dodatku: {addon_id!r}.")
    if not version or any(char in version for char in "/\\"):
        raise RepoError(f"{source}: nieprawidłowa wersja dodatku: {version!r}.")
    return root


def safe_zip_members(zf: zipfile.ZipFile, source: Path) -> list[str]:
    names: list[str] = []
    for info in zf.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise RepoError(f"{source.name}: niebezpieczna ścieżka ZIP: {info.filename!r}.")
        names.append(info.filename)
    return names


def inspect_addon_zip(zip_path: Path) -> AddonArchive:
    zip_path = zip_path.expanduser().resolve()
    if not zip_path.is_file():
        raise RepoError(f"Nie znaleziono pliku: {zip_path}")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = safe_zip_members(zf, zip_path)
            broken = zf.testzip()
            if broken:
                raise RepoError(f"{zip_path.name}: uszkodzony plik w archiwum: {broken}")

            manifests = [
                name
                for name in names
                if not name.endswith("/")
                and len(PurePosixPath(name).parts) == 2
                and PurePosixPath(name).name == "addon.xml"
            ]
            if len(manifests) != 1:
                raise RepoError(
                    f"{zip_path.name}: oczekiwano jednego <addon_id>/addon.xml, "
                    f"znaleziono {len(manifests)}."
                )

            manifest_name = manifests[0]
            manifest_text = zf.read(manifest_name).decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeDecodeError, OSError) as exc:
        raise RepoError(f"Nie można odczytać {zip_path.name}: {exc}") from exc

    manifest = parse_manifest(manifest_text, f"{zip_path.name}/addon.xml")
    addon_id = manifest.get("id", "").strip()
    version = manifest.get("version", "").strip()
    root_dir = PurePosixPath(manifest_name).parts[0]
    if root_dir != addon_id:
        raise RepoError(
            f"{zip_path.name}: katalog główny {root_dir!r} nie zgadza się "
            f"z ID dodatku {addon_id!r}."
        )

    return AddonArchive(
        path=zip_path,
        addon_id=addon_id,
        version=version,
        root_dir=root_dir,
        manifest_text=manifest_text,
        manifest=manifest,
    )


def version_key(version: str) -> tuple[tuple[int, object], ...]:
    """Naturalne sortowanie wersji; poprawnie rozróżnia np. 2.0.9 i 2.0.52."""
    parts = re.findall(r"\d+|[A-Za-z]+", version)
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in parts
    )


def asset_paths(manifest: ET.Element) -> list[PurePosixPath]:
    result: list[PurePosixPath] = []
    for assets in manifest.findall("./extension[@point='xbmc.addon.metadata']/assets"):
        for asset in assets:
            value = (asset.text or "").strip()
            if not value:
                continue
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts:
                raise RepoError(f"Niebezpieczna ścieżka grafiki w addon.xml: {value!r}.")
            if path not in result:
                result.append(path)
    return result


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def copy_assets(archive: AddonArchive, destination: Path) -> None:
    assets = asset_paths(archive.manifest)
    if not assets:
        print(f"  UWAGA: {archive.addon_id} nie deklaruje grafik w <assets>.")
        return

    with zipfile.ZipFile(archive.path, "r") as zf:
        names = set(zf.namelist())
        for relative in assets:
            member = f"{archive.root_dir}/{relative.as_posix()}"
            if member not in names:
                raise RepoError(
                    f"{archive.path.name}: brak zadeklarowanej grafiki {relative}."
                )
            target = destination.joinpath(*relative.parts)
            atomic_write(target, zf.read(member))


def import_archive(archive: AddonArchive) -> AddonArchive:
    destination = ZIPS_DIR / archive.addon_id
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / archive.canonical_name

    if archive.path != target.resolve():
        temp_target = destination / f".{archive.canonical_name}.tmp"
        shutil.copy2(archive.path, temp_target)
        os.replace(temp_target, target)
    archive = inspect_addon_zip(target)
    copy_assets(archive, destination)

    print(f"  Dodano paczkę: {target.relative_to(REPO_DIR)}")
    return archive


def scan_latest_archives(copy_latest_assets: bool) -> dict[str, AddonArchive]:
    if not ZIPS_DIR.is_dir():
        raise RepoError(f"Brak katalogu z paczkami: {ZIPS_DIR}")

    latest: dict[str, AddonArchive] = {}
    for addon_dir in sorted(ZIPS_DIR.iterdir(), key=lambda path: path.name.casefold()):
        if not addon_dir.is_dir():
            continue

        archives: list[AddonArchive] = []
        for zip_path in sorted(addon_dir.glob("*.zip"), key=lambda path: path.name.casefold()):
            archive = inspect_addon_zip(zip_path)
            if archive.addon_id != addon_dir.name:
                raise RepoError(
                    f"{zip_path}: ID {archive.addon_id!r} nie zgadza się "
                    f"z katalogiem {addon_dir.name!r}."
                )
            if zip_path.name != archive.canonical_name:
                raise RepoError(
                    f"{zip_path}: nazwa powinna brzmieć {archive.canonical_name!r}."
                )
            archives.append(archive)

        if not archives:
            continue

        selected = max(archives, key=lambda item: version_key(item.version))
        latest[selected.addon_id] = selected
        print(f"  Najnowsza paczka: {selected.canonical_name}")
        older = [item.canonical_name for item in archives if item.path != selected.path]
        if older:
            print(f"    starsze pozostają w repo: {', '.join(older)}")
        if copy_latest_assets:
            copy_assets(selected, addon_dir)

    return latest


def repo_manifest() -> tuple[str, ET.Element]:
    if not REPO_ADDON_XML.is_file():
        raise RepoError(f"Brak pliku repozytorium: {REPO_ADDON_XML}")
    text = REPO_ADDON_XML.read_text(encoding="utf-8-sig")
    manifest = parse_manifest(text, str(REPO_ADDON_XML))
    return text, manifest


def sync_repository_manifest(
    archives: dict[str, AddonArchive],
    check_only: bool,
) -> ET.Element:
    """Synchronizuje główny addon.xml z najnowszą paczką repozytorium.

    Kodi odczytuje wersję repozytorium z addons.xml, a ten plik jest
    generowany z głównego addon.xml. Jeśli do zips/repository... trafi
    nowszy ZIP repozytorium, ale główny addon.xml pozostanie stary,
    Kodi nie zobaczy aktualizacji.

    Ta funkcja automatycznie pobiera addon.xml z najnowszego ZIP-a
    repozytorium i zapisuje go jako główny addon.xml. W trybie --check
    niczego nie zapisuje, tylko zgłasza niespójność.
    """
    current_text, current_manifest = repo_manifest()
    repository_id = current_manifest.get("id", "").strip()
    repository_archive = archives.get(repository_id)

    if repository_archive is None:
        return current_manifest

    archive_text = repository_archive.manifest_text
    archive_manifest = repository_archive.manifest

    current_normalized = sanitize_xml(current_text).strip()
    archive_normalized = sanitize_xml(archive_text).strip()

    if current_normalized == archive_normalized:
        return current_manifest

    current_version = current_manifest.get("version", "").strip()
    archive_version = archive_manifest.get("version", "").strip()

    if version_key(archive_version) < version_key(current_version):
        raise RepoError(
            f"Najnowsza paczka {repository_archive.canonical_name} ma starszą "
            f"wersję ({archive_version}) niż główny addon.xml ({current_version})."
        )

    if check_only:
        raise RepoError(
            f"Główny addon.xml repozytorium jest niespójny z "
            f"{repository_archive.canonical_name}. Uruchom skrypt bez --check, "
            "aby zsynchronizować pliki."
        )

    data = archive_text.encode("utf-8")
    atomic_write(REPO_ADDON_XML, data)
    print(
        f"  Zsynchronizowano addon.xml repozytorium: "
        f"{current_version or '?'} -> {archive_version}"
    )

    # Parsujemy jeszcze raz zawartość, która faktycznie została zapisana.
    return parse_manifest(archive_text, str(REPO_ADDON_XML))


def render_repository(
    copy_latest_assets: bool,
    check_only: bool,
) -> tuple[bytes, bytes, list[AddonArchive]]:
    archives = scan_latest_archives(copy_latest_assets)
    repository = sync_repository_manifest(archives, check_only=check_only)
    repository_id = repository.get("id", "")

    root = ET.Element("addons")
    root.append(repository)
    selected: list[AddonArchive] = []
    for addon_id in sorted(archives, key=str.casefold):
        archive = archives[addon_id]
        if addon_id == repository_id:
            print(
                f"  Paczka {archive.canonical_name} służy do aktualizacji repo; "
                "jej manifest nie jest dodawany drugi raz."
            )
            continue
        root.append(ET.fromstring(sanitize_xml(archive.manifest_text)))
        selected.append(archive)

    ET.indent(root, space="    ")
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )
    xml_bytes = xml_text.encode("utf-8")
    md5_bytes = hashlib.md5(xml_bytes).hexdigest().encode("ascii")
    return xml_bytes, md5_bytes, selected


def validate_assets(archives: list[AddonArchive]) -> None:
    for archive in archives:
        directory = ZIPS_DIR / archive.addon_id
        for relative in asset_paths(archive.manifest):
            path = directory.joinpath(*relative.parts)
            if not path.is_file() or path.stat().st_size == 0:
                raise RepoError(f"Brak grafiki repozytorium: {path}")


def check_current(expected_xml: bytes, expected_md5: bytes) -> None:
    problems: list[str] = []
    if not ADDONS_XML.is_file() or ADDONS_XML.read_bytes() != expected_xml:
        problems.append("addons.xml jest nieaktualny")
    if not ADDONS_MD5.is_file() or ADDONS_MD5.read_bytes() != expected_md5:
        problems.append("addons.xml.md5 jest nieaktualny")
    if problems:
        raise RepoError("; ".join(problems) + ". Uruchom skrypt bez --check.")


def build(imports: list[Path], check_only: bool) -> None:
    print("\n=== Repozytorium Kadr+ ===\n")
    if check_only and imports:
        raise RepoError("--check nie może być łączone z dodawaniem ZIP-ów.")

    # Najpierw sprawdź istniejące paczki, żeby nowy ZIP nie został skopiowany
    # do repozytorium, które już wcześniej było niespójne.
    if imports and ZIPS_DIR.is_dir():
        scan_latest_archives(copy_latest_assets=False)

    inspected_imports = [inspect_addon_zip(zip_path) for zip_path in imports]
    imported_ids: set[str] = set()
    for archive in inspected_imports:
        if archive.addon_id in imported_ids:
            raise RepoError(
                f"Podano więcej niż jedną nową paczkę dodatku {archive.addon_id!r}."
            )
        imported_ids.add(archive.addon_id)
    for archive in inspected_imports:
        import_archive(archive)

    xml_bytes, md5_bytes, selected = render_repository(
        copy_latest_assets=not check_only,
        check_only=check_only,
    )
    validate_assets(selected)

    if check_only:
        check_current(xml_bytes, md5_bytes)
        print("\n  OK: paczki, grafiki, addons.xml i MD5 są spójne.")
        return

    atomic_write(ADDONS_XML, xml_bytes)
    atomic_write(ADDONS_MD5, md5_bytes)
    print(f"\n  Zapisano: {ADDONS_XML.relative_to(REPO_DIR)}")
    print(f"  Zapisano: {ADDONS_MD5.relative_to(REPO_DIR)}")
    print(f"  MD5: {expected_md5_text(md5_bytes)}")
    print("\n=== Gotowe lokalnie. Sprawdź git status, commit i push. ===\n")


def expected_md5_text(md5_bytes: bytes) -> str:
    return md5_bytes.decode("ascii").strip()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dodaje paczki i generuje addons.xml dla repozytorium Kadr+."
    )
    parser.add_argument(
        "zip_files",
        metavar="ZIP",
        nargs="*",
        type=Path,
        help="paczka dodatku do dodania, np. plugin.video.kadrplus2-2.0.52.zip",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="tylko sprawdź repozytorium; niczego nie zapisuj",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        build(args.zip_files, args.check)
    except RepoError as exc:
        print(f"\nBŁĄD: {exc}\n", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"\nBŁĄD systemu plików: {exc}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
