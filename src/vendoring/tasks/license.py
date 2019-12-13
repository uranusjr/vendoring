import tarfile
import zipfile
from pathlib import Path

import requests

from vendoring.ui import UI
from vendoring.utils import remove_all, run


def download_sources(destination, requirements_path):
    cmd = [
        "pip",
        "download",
        "-r",
        str(requirements_path),
        "--no-binary",
        ":all:",
        "--no-deps",
        "--dest",
        str(destination),
    ]
    run(cmd, working_directory=None)


def libname_from_dir(dirname):
    """Reconstruct the library name without it's version"""
    parts = []
    for part in dirname.split("-"):
        if part[0].isdigit():
            break
        parts.append(part)
    return "-".join(parts)


def extract_license_member(target_dir, tar, member, name, license_directories):
    mpath = Path(name)  # relative path inside the sdist

    dirname = list(mpath.parents)[-2].name  # -1 is .
    libname = libname_from_dir(dirname)

    dest = license_destination(target_dir, libname, mpath.name, license_directories)

    UI.log("Extracting {} into {}".format(name, dest.relative_to(target_dir)))
    try:
        fileobj = tar.extractfile(member)
        dest.write_bytes(fileobj.read())
    except AttributeError:  # zipfile
        dest.write_bytes(tar.read(member))


def find_and_extract_license(target_dir, tar, members, license_directories):
    found = False
    for member in members:
        try:
            license_directories,
            name = member.name
        except AttributeError:  # zipfile
            name = member.filename
        if "LICENSE" in name or "COPYING" in name:
            if "/test" in name:
                # some testing licenses in html5lib and distlib
                UI.log("Ignoring {}".format(name))
                continue
            found = True
            extract_license_member(target_dir, tar, member, name, license_directories)
    return found


def license_destination(target_dir, libname, filename, license_directories):
    """Given the (reconstructed) library name, find appropriate destination"""
    normal = target_dir / libname
    if normal.is_dir():
        return normal / filename
    lowercase = target_dir / libname.lower()
    if lowercase.is_dir():
        return lowercase / filename
    if libname in license_directories:
        return target_dir / license_directories[libname] / filename
    # fallback to libname.LICENSE (used for nondirs)
    return target_dir / "{}.{}".format(libname, filename)


def download_url(url, dest):
    UI.log("Downloading {}".format(url))
    r = requests.get(url, allow_redirects=True)
    r.raise_for_status()
    dest.write_bytes(r.content)


def license_fallback(
    target_dir, sdist_name, license_directories, license_fallback_urls
):
    """Hardcoded license URLs. Check when updating if those are still needed"""
    libname = libname_from_dir(sdist_name)
    if libname not in license_fallback_urls:
        raise ValueError("No hardcoded URL for {} license".format(libname))

    url = license_fallback_urls[libname]
    _, _, name = url.rpartition("/")
    dest = license_destination(target_dir, libname, name, license_directories)

    download_url(url, dest)


def extract_license(target_dir, sdist, license_directories, license_fallback_urls):
    def extract_from_source_tarfile(sdist):
        ext = sdist.suffixes[-1][1:]
        with tarfile.open(sdist, mode="r:{}".format(ext)) as tar:
            return find_and_extract_license(
                target_dir, tar, tar.getmembers(), license_directories,
            )

    def extract_from_source_zipfile(sdist):
        with zipfile.ZipFile(sdist) as zip:
            return find_and_extract_license(
                target_dir, zip, zip.infolist(), license_directories,
            )

    if sdist.suffixes[-2] == ".tar":
        found = extract_from_source_tarfile(sdist)
    elif sdist.suffixes[-1] == ".zip":
        found = extract_from_source_zipfile(sdist)
    else:
        raise NotImplementedError("new sdist type!")

    if found:
        return

    UI.log("License not found in {}".format(sdist.name))
    license_fallback(target_dir, sdist.name, license_directories, license_fallback_urls)


def fetch_licenses(config):
    target_dir = config.target_dir
    license_directories = config.license_directories
    license_fallback_urls = config.license_fallback_urls
    requirements_path = config.requirements_path

    tmp_dir = target_dir / "__tmp__"
    download_sources(tmp_dir, requirements_path)

    for sdist in tmp_dir.iterdir():
        extract_license(target_dir, sdist, license_directories, license_fallback_urls)

    remove_all([tmp_dir])
