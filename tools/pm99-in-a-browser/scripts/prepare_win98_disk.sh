#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DISK="${ROOT}/v86/assets/disks/win98-pm99.img"
DISK_SIZE="2G"
MEMORY_MB="128"
INSTALLER_ISO=""
BOOT_FLOPPY=""
PM99_ISO="${ROOT}/v86/assets/media/pm99.iso"
COMMAND="${1:-install}"

if [[ "${COMMAND}" != "create" && "${COMMAND}" != "install" && "${COMMAND}" != "boot" ]]; then
  COMMAND="install"
else
  shift || true
fi

usage() {
  cat <<'USAGE'
Usage: scripts/prepare_win98_disk.sh <command> [options]

Create and boot a local Windows 98 disk image for the v86 PM99 profile.
This script never downloads Windows. Use your own licensed Windows 98 install
ISO/CD image and, for non-bootable CDs, a Windows 98 boot floppy image.

Commands:
  create              Create the sparse raw disk image only.
  install             Create the disk if needed, then boot Win98 install media.
  boot                Boot the installed disk, optionally with PM99 media.

Options:
  --disk <path>       Raw disk image path (default: v86/assets/disks/win98-pm99.img)
  --size <size>       qemu-img disk size for new images (default: 2G)
  --memory <MiB>      QEMU memory in MiB (default: 128)
  --installer-iso <path>
                      Windows 98 install ISO/CD image for the install command.
  --boot-floppy <path>
                      Windows 98 boot floppy image; boot order becomes floppy first.
  --pm99-iso <path>   PM99 ISO to attach when booting installed Windows.
  -h, --help          Show this help.

Examples:
  scripts/prepare_win98_disk.sh create
  scripts/prepare_win98_disk.sh install --installer-iso ~/.local/win98/WIN98SE.iso --boot-floppy ~/.local/win98/boot98se.img
  scripts/prepare_win98_disk.sh boot
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --disk) DISK="$2"; shift 2 ;;
    --size) DISK_SIZE="$2"; shift 2 ;;
    --memory) MEMORY_MB="$2"; shift 2 ;;
    --installer-iso) INSTALLER_ISO="$2"; shift 2 ;;
    --boot-floppy) BOOT_FLOPPY="$2"; shift 2 ;;
    --pm99-iso) PM99_ISO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required tool: $1" >&2
    exit 1
  fi
}

abs_path() {
  local path="$1"
  if [[ "${path}" = /* ]]; then
    printf '%s\n' "${path}"
  else
    printf '%s\n' "$(pwd)/${path}"
  fi
}

create_disk() {
  require_tool qemu-img
  mkdir -p "$(dirname "${DISK}")"
  if [[ -e "${DISK}" ]]; then
    echo "Disk already exists: ${DISK}"
    return
  fi
  qemu-img create -f raw "${DISK}" "${DISK_SIZE}"
  echo "Created sparse raw disk: ${DISK}"
}

qemu_base_args() {
  printf '%s\0' \
    qemu-system-i386 \
    -name "PM99 Windows 98 prep" \
    -M pc \
    -cpu pentium2 \
    -m "${MEMORY_MB}" \
    -rtc base=localtime \
    -vga cirrus \
    -net none \
    -drive "file=${DISK},format=raw,if=ide,index=0,media=disk"
}

run_qemu_install() {
  require_tool qemu-system-i386
  if [[ -z "${INSTALLER_ISO}" ]]; then
    echo "install requires --installer-iso <path> for your local Windows 98 media" >&2
    exit 2
  fi
  if [[ ! -f "${INSTALLER_ISO}" ]]; then
    echo "Installer ISO not found: ${INSTALLER_ISO}" >&2
    exit 1
  fi
  local args=()
  while IFS= read -r -d '' item; do args+=("${item}"); done < <(qemu_base_args)
  args+=(-drive "file=$(abs_path "${INSTALLER_ISO}"),media=cdrom,if=ide,index=2,readonly=on")
  if [[ -n "${BOOT_FLOPPY}" ]]; then
    if [[ ! -f "${BOOT_FLOPPY}" ]]; then
      echo "Boot floppy not found: ${BOOT_FLOPPY}" >&2
      exit 1
    fi
    args+=(-drive "file=$(abs_path "${BOOT_FLOPPY}"),format=raw,if=floppy,index=0,readonly=on" -boot order=a)
  else
    args+=(-boot order=d)
  fi

  echo "Starting QEMU installer. Partition/format/install Windows 98 inside the guest."
  echo "After Windows shuts down, run: scripts/inject_pm99_into_win98_disk.py"
  "${args[@]}"
}

run_qemu_boot() {
  require_tool qemu-system-i386
  if [[ ! -f "${DISK}" ]]; then
    echo "Disk image not found: ${DISK}" >&2
    exit 1
  fi
  local args=()
  while IFS= read -r -d '' item; do args+=("${item}"); done < <(qemu_base_args)
  if [[ -f "${PM99_ISO}" ]]; then
    args+=(-drive "file=$(abs_path "${PM99_ISO}"),media=cdrom,if=ide,index=2,readonly=on")
  fi
  args+=(-boot order=c)

  echo "Starting installed Windows 98 disk in QEMU."
  "${args[@]}"
}

case "${COMMAND}" in
  create)
    create_disk
    ;;
  install)
    create_disk
    run_qemu_install
    ;;
  boot)
    run_qemu_boot
    ;;
esac
