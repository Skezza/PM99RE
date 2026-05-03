# Windows 98 Disk Prep

This workflow prepares a local-only Windows 98 hard disk image for the v86 PM99
profile. It does not download Windows 98, create a license, or commit any guest
image. Bring your own licensed Windows 98 install media.

## 1. Stage PM99 And Emulator Payloads

```bash
cd tools/pm99-in-a-browser
./scripts/prepare_pm99_assets.sh --source ../../work/fixtures/premier-manager-ninety-nine-pristine
npm install
npm run payloads:open
```

## 2. Create The Blank v86 Disk

```bash
./scripts/prepare_win98_disk.sh create
```

This creates a sparse raw IDE image at:

```text
v86/assets/disks/win98-pm99.img
```

The path is ignored by Git.

## 3. Install Windows 98 In QEMU

With a bootable Windows 98 ISO:

```bash
./scripts/prepare_win98_disk.sh install --installer-iso /path/to/WIN98SE.iso
```

With a non-bootable CD ISO plus a Windows 98 boot floppy image:

```bash
./scripts/prepare_win98_disk.sh install \
  --installer-iso /path/to/WIN98SE.iso \
  --boot-floppy /path/to/boot98se.img
```

Inside the guest, use the normal Windows 98 setup flow:

- enable large disk support if `FDISK` asks
- create a primary DOS partition
- reboot the installer when prompted
- format `C:`
- run `SETUP.EXE` from the Windows 98 media
- keep the first pass boring: VGA/Cirrus display, 640x480 or 800x600, 16-bit
  color, no network

Shut Windows down cleanly after setup completes.

## 4. Inject PM99 Into The Installed Disk

```bash
python3 scripts/inject_pm99_into_win98_disk.py
```

The injector detects the first FAT16/FAT32 partition and copies the staged PM99
tree to:

```text
C:\PM99
```

It also writes:

```text
C:\PM99\RUNPM99.BAT
```

## 5. Boot And Verify In QEMU

```bash
./scripts/prepare_win98_disk.sh boot
```

Run `C:\PM99\RUNPM99.BAT` inside Windows. Confirm the game reaches its title
screen before trying v86.

## 6. Boot In Browser

```bash
./scripts/serve.sh
```

Open:

```text
http://127.0.0.1:8099/v86/
```

Use the `Windows 98 + PM99` profile.

## Notes

- The default disk size is 2 GiB to stay within old Windows 98/FAT expectations
  and to match `v86/configs/windows98-pm99.json`.
- If you choose a different disk size, update the `hda.size` field in the v86
  profile.
- The disk image, Windows media, PM99 ISO, v86 runtime, and BIOS blobs are all
  local ignored payloads.
