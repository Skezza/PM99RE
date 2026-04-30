# PM99 v86 Browser Prototype

This is a static v86 backend scaffold for proving whether a licensed Windows
98 or Windows 2000 guest can run PM99 in a browser. It intentionally contains
no v86 vendor build, Windows image, PM99 image, PM99 data, or PM99 executable.

## Layout

```text
tools/pm99-in-a-browser/v86/
  index.html                 browser launcher UI
  js/v86-launcher.js          zero-dependency launcher module
  configs/
    windows98-pm99.json       installed Windows 98 + mounted PM99 media example
    windows2000-pm99.json     installed Windows 2000 + mounted PM99 media example
  vendor/
    libv86.js                 local only, not committed
    v86.wasm                  local only, not committed
  assets/
    bios/
      seabios.bin             local only, not committed
      vgabios.bin             local only, not committed
    disks/
      win98-pm99.img          local only, not committed
      win2000-pm99.img        local only, not committed
    media/
      pm99.iso                local only, not committed
```

## Local Setup

1. Build or download v86 separately, then copy `libv86.js` and `v86.wasm` into
   `vendor/`.
2. Copy compatible v86 BIOS files into `assets/bios/`.
3. Create a licensed Windows 98 or Windows 2000 disk image with PM99 installed
   or ready to install, then place it in `assets/disks/`.
4. Place the PM99 CD/image or install media in `assets/media/`.
5. Edit the matching file in `configs/` if local filenames or memory sizes
   differ.
6. Serve this directory over HTTP:

```sh
cd tools/pm99-in-a-browser/v86
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`. Do not use `file://`; v86 loads ROMs and disk
images through browser fetch/XHR paths.

## Notes

- The examples boot from hard disk first and mount PM99 media as the CD-ROM.
- Large disk images can use v86 async images, but the config must include the
  exact byte size. The examples use non-async image loading for readability.
- Windows 2000 guests should be installed/configured as a Standard PC rather
  than an ACPI PC for v86 compatibility.
- PM99 media can be swapped at runtime with the launcher CD-ROM file input, but
  boot disks still need to be referenced by the config at launch time.
