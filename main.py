from apkmirror import Version, Variant
from build_variants import build_apks          # unchanged, from build_variants.py
from download_bins import download_apkeditor, download_morphe_cli, download_release_asset
import github
from utils import panic, merge_apk, publish_release, patch_apk
import apkmirror
import os
import argparse
import subprocess


def compress_apk_with_7z(apk_file: str) -> str:
    """
    Compress a single APK file with maximum 7z compression
    Returns the compressed file path
    """
    compressed_file = f"{apk_file}.7z"
    
    cmd = [
        "7z", "a",
        "-t7z",
        "-m0=lzma2",
        "-mx=9",
        "-mfb=64",
        "-md=32m",
        "-ms=on",
        "-mmt=on",
        compressed_file,
        apk_file
    ]
    
    print(f"Compressing {apk_file} with 7z...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"7z compression failed for {apk_file}: {result.stderr}")
        return None
    
    print(f"Compressed to {compressed_file}")
    return compressed_file


# ---- MORPHE REPATCH: new helpers -----------------------------------
def get_morphe_patches() -> str:
    """
    Downloads the latest morphe-patches asset from kareemlukitomo/morphe-patches
    and returns the local file path.
    Adjust the regex if the file extension is .jar or .rvp.
    """
    print("Downloading Morphe patches")
    release_info = download_release_asset(
        repo="kareemlukitomo/morphe-patches",
        regex=r"^patches.*mpp$",   # change to .jar if needed
        out_dir="bins",
        filename="morphe-patches.mpp",
        include_prereleases=False
    )
    return os.path.join("bins", "morphe-patches.rvp")


def add_morphe_patch(version: str) -> str | None:
    """
    Applies only the 'Disable Twitter PairlP startup checks' patch
    to the already Piko-patched twitter-piko APK.
    Returns the path of the newly created APK, or None if the base APK is missing.
    """
    base_apk = f"twitter-piko-v{version}.apk"
    if not os.path.exists(base_apk):
        print(f"Warning: {base_apk} not found, skipping morphe repatch")
        return None

    morphe_patches = os.path.join("bins", "morphe-patches.rvp")
    cli = os.path.join("bins", "morphe-cli.jar")   # already downloaded by download_morphe_cli()

    out_apk = f"twitter-piko-morphe-v{version}.apk"

    print(f"Applying Morphe patch to {base_apk} ...")
    patch_apk(
        cli=cli,
        patches=morphe_patches,
        apk=base_apk,
        includes=["Disable Twitter PairlP startup checks"],  # exact patch name
        out=out_apk,
        excludes=None,
    )

    if not os.path.exists(out_apk):
        print("Error: Morphe patching failed to produce output")
        return None
    return out_apk
# -------------------------------------------------------------------


def get_latest_release(versions: list[Version]) -> Version | None:
    for i in versions:
        if i.version.find("release") >= 0:
            return i


def process(latest_version: Version):
    variants: list[Variant] = apkmirror.get_variants(latest_version)

    download_link: Variant | None = None
    for variant in variants:
        if variant.is_bundle and ("universal" in variant.architecture or "arm64-v8a" in variant.architecture):
            download_link = variant
            break

    if download_link is None:
        raise Exception("Bundle not Found")

    apkmirror.download_apk(download_link)
    if not os.path.exists("big_file.apkm"):
        panic("Failed to download apk")

    download_apkeditor()

    if not os.path.exists("big_file_merged.apk"):
        merge_apk("big_file.apkm")
    else:
        print("apkm is already merged")

    download_morphe_cli(include_prereleases=True)

    print("Downloading patches")
    pikoRelease = download_release_asset(
        "crimera/piko", "^patches.*mpp$", "bins", "patches.mpp", include_prereleases=True
    )

    message: str = f"""
Changelogs:
[piko-{pikoRelease["tag_name"]}]({pikoRelease["html_url"]})
"""

    build_apks(latest_version)          # <-- original Piko patching (unchanged)

    # ---- MORPHE REPATCH --------------------------------------------
    get_morphe_patches()
    morphe_apk = add_morphe_patch(latest_version.version)
    if morphe_apk:
        message += "\n**Additional patch:** Disable Twitter PairlP startup checks (Morphe)"
    # -----------------------------------------------------------------

    apk_files = [
        f"x-piko-v{latest_version.version}.apk",
        f"x-piko-material-you-v{latest_version.version}.apk",
        f"twitter-piko-v{latest_version.version}.apk",
        f"twitter-piko-material-you-v{latest_version.version}.apk",
    ]
    if morphe_apk and os.path.exists(morphe_apk):
        apk_files.append(morphe_apk)

    compressed_files = []
    for apk_file in apk_files:
        if os.path.exists(apk_file):
            compressed_file = compress_apk_with_7z(apk_file)
            if compressed_file and os.path.exists(compressed_file):
                compressed_files.append(compressed_file)
        else:
            print(f"Warning: {apk_file} not found, skipping compression")

    if not compressed_files:
        panic("No compressed files were created successfully")
        return

    publish_release(
        latest_version.version,
        compressed_files,
        message,
        latest_version.version
    )


def main():
    url: str = "https://www.apkmirror.com/apk/x-corp/twitter/"
    repo_url: str = "lluni/twitter-apk"

    versions = apkmirror.get_versions(url)

    latest_version = get_latest_release(versions)
    if latest_version is None:
        raise Exception("Could not find the latest version")

    if latest_version.version.find("release") < 0:
        panic("Latest version is not a release version")

    last_build_version: github.GithubRelease | None = github.get_last_build_version(
        repo_url
    )

    if last_build_version is None:
        panic("Failed to fetch the latest build version")
        return

    if last_build_version.tag_name != latest_version.version:
        print(f"New version found: {latest_version.version}")
    else:
        print("No new version found")
        return

    process(latest_version)


def manual(version:str):
    link = f'https://www.apkmirror.com/apk/x-corp/twitter/x-{version.replace(".","-")}-release'
    latest_version = Version(link=link,version=version)
    process(latest_version)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Piko APK')
    parser.add_argument('--m', action="store", dest='mode', default=0)
    parser.add_argument('--v', action="store", dest='version', default=0)

    args = parser.parse_args()
    mode = args.mode

    if not mode:
        main()
    else:
        version = args.version
        if not version:
            raise Exception("Version is required.")
        manual(version)
