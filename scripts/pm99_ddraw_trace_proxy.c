#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <ddraw.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

typedef HRESULT (WINAPI *PFN_DirectDrawCreate)(GUID *, LPDIRECTDRAW *, IUnknown *);
typedef HRESULT (WINAPI *PFN_DirectDrawCreateEx)(GUID *, LPVOID *, REFIID, IUnknown *);
typedef HRESULT (WINAPI *PFN_DirectDrawEnumerateA)(LPDDENUMCALLBACKA, LPVOID);
typedef HRESULT (WINAPI *PFN_DirectDrawEnumerateExA)(LPDDENUMCALLBACKEXA, LPVOID, DWORD);

typedef struct TraceDirectDraw {
    IDirectDraw iface;
    LPDIRECTDRAW real;
    LONG refs;
} TraceDirectDraw;

typedef struct TraceDirectDraw4 {
    IDirectDraw4 iface;
    LPDIRECTDRAW4 real;
    LONG refs;
} TraceDirectDraw4;

typedef struct EnumModesContext {
    LPDDENUMMODESCALLBACK callback;
    LPVOID context;
    DWORD seen;
    DWORD passed;
    DWORD filtered;
    const char *source;
} EnumModesContext;

typedef struct EnumModes2Context {
    LPDDENUMMODESCALLBACK2 callback;
    LPVOID context;
    DWORD seen;
    DWORD passed;
    DWORD filtered;
    const char *source;
} EnumModes2Context;

static const GUID PM99_IID_IDirectDraw4 = {
    0x9c59509a,
    0x39bd,
    0x11d1,
    {0x8c, 0x4a, 0x00, 0xc0, 0x4f, 0xd9, 0x30, 0xc5}
};

static HMODULE real_ddraw_module;
static PFN_DirectDrawCreate real_DirectDrawCreate;
static PFN_DirectDrawCreateEx real_DirectDrawCreateEx;
static PFN_DirectDrawEnumerateA real_DirectDrawEnumerateA;
static PFN_DirectDrawEnumerateExA real_DirectDrawEnumerateExA;

static void trace_log(const char *fmt, ...)
{
    char path[MAX_PATH * 2];
    const char *env_path = getenv("PM99_DDRAW_TRACE_LOG");
    FILE *fh;
    va_list ap;

    if (env_path && env_path[0]) {
        lstrcpynA(path, env_path, sizeof(path));
    } else {
        lstrcpynA(path, "pm99-ddraw.log", sizeof(path));
    }

    fh = fopen(path, "a");
    if (!fh) {
        return;
    }

    fprintf(fh, "[%lu][tid=%lu] ", GetTickCount(), GetCurrentThreadId());
    va_start(ap, fmt);
    vfprintf(fh, fmt, ap);
    va_end(ap);
    fputc('\n', fh);
    fclose(fh);
}

static const char *hr_state(HRESULT hr)
{
    return SUCCEEDED(hr) ? "ok" : "fail";
}

static int env_flag_enabled(const char *name)
{
    const char *value = getenv(name);
    if (!value || !value[0]) {
        return 0;
    }
    return lstrcmpiA(value, "1") == 0
        || lstrcmpiA(value, "true") == 0
        || lstrcmpiA(value, "yes") == 0
        || lstrcmpiA(value, "on") == 0;
}

static int enum_mode_filter_enabled(void)
{
    return env_flag_enabled("PM99_DDRAW_FILTER_ENUM_MODES_640");
}

static int enum_mode_injection_enabled(void)
{
    return env_flag_enabled("PM99_DDRAW_INJECT_ENUM_MODE_640");
}

static int force_set_display_mode_ok_enabled(void)
{
    return env_flag_enabled("PM99_DDRAW_FORCE_SET_DISPLAY_MODE_OK");
}

static int mode_desc_matches_640x480x16(LPDDSURFACEDESC desc)
{
    if (!desc) {
        return 0;
    }
    return desc->dwWidth == 640
        && desc->dwHeight == 480
        && desc->ddpfPixelFormat.dwRGBBitCount == 16;
}

static int mode_desc2_matches_640x480x16(LPDDSURFACEDESC2 desc)
{
    if (!desc) {
        return 0;
    }
    return desc->dwWidth == 640
        && desc->dwHeight == 480
        && desc->ddpfPixelFormat.dwRGBBitCount == 16;
}

static void fill_synthetic_640x480x16_desc(LPDDSURFACEDESC desc)
{
    ZeroMemory(desc, sizeof(*desc));
    desc->dwSize = sizeof(*desc);
    desc->dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_PITCH | DDSD_PIXELFORMAT;
    desc->dwWidth = 640;
    desc->dwHeight = 480;
    desc->lPitch = 1280;
    desc->ddpfPixelFormat.dwSize = sizeof(DDPIXELFORMAT);
    desc->ddpfPixelFormat.dwFlags = DDPF_RGB;
    desc->ddpfPixelFormat.dwRGBBitCount = 16;
    desc->ddpfPixelFormat.dwRBitMask = 0x0000F800;
    desc->ddpfPixelFormat.dwGBitMask = 0x000007E0;
    desc->ddpfPixelFormat.dwBBitMask = 0x0000001F;
}

static void fill_synthetic_640x480x16_desc2(LPDDSURFACEDESC2 desc)
{
    ZeroMemory(desc, sizeof(*desc));
    desc->dwSize = sizeof(*desc);
    desc->dwFlags = DDSD_WIDTH | DDSD_HEIGHT | DDSD_PITCH | DDSD_PIXELFORMAT;
    desc->dwWidth = 640;
    desc->dwHeight = 480;
    desc->lPitch = 1280;
    desc->ddpfPixelFormat.dwSize = sizeof(DDPIXELFORMAT);
    desc->ddpfPixelFormat.dwFlags = DDPF_RGB;
    desc->ddpfPixelFormat.dwRGBBitCount = 16;
    desc->ddpfPixelFormat.dwRBitMask = 0x0000F800;
    desc->ddpfPixelFormat.dwGBitMask = 0x000007E0;
    desc->ddpfPixelFormat.dwBBitMask = 0x0000001F;
}

static HRESULT maybe_force_set_display_mode_ok(HRESULT real_hr, DWORD width, DWORD height, DWORD bpp, const char *source)
{
    if (
        FAILED(real_hr)
        && force_set_display_mode_ok_enabled()
        && width == 640
        && height == 480
        && bpp == 16
    ) {
        trace_log("%s force_set_display_mode_ok real_hr=0x%08lX returning DD_OK", source, (unsigned long)real_hr);
        return DD_OK;
    }
    return real_hr;
}

static void normalize_display_mode_desc(LPDDSURFACEDESC desc, const char *source)
{
    if (!desc || !env_flag_enabled("PM99_DDRAW_NORMALIZE_DISPLAY_MODE")) {
        return;
    }
    trace_log(
        "%s normalize_display_mode before width=%lu height=%lu pitch=%ld rgbbits=%lu flags=0x%08lX",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->ddpfPixelFormat.dwRGBBitCount,
        desc->dwFlags
    );
    desc->dwFlags |= DDSD_WIDTH | DDSD_HEIGHT | DDSD_PITCH | DDSD_PIXELFORMAT;
    desc->dwWidth = 640;
    desc->dwHeight = 480;
    desc->lPitch = 1280;
    desc->ddpfPixelFormat.dwSize = sizeof(DDPIXELFORMAT);
    desc->ddpfPixelFormat.dwFlags = DDPF_RGB;
    desc->ddpfPixelFormat.dwRGBBitCount = 16;
    desc->ddpfPixelFormat.dwRBitMask = 0x0000F800;
    desc->ddpfPixelFormat.dwGBitMask = 0x000007E0;
    desc->ddpfPixelFormat.dwBBitMask = 0x0000001F;
    trace_log(
        "%s normalize_display_mode after width=%lu height=%lu pitch=%ld rgbbits=%lu flags=0x%08lX",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->ddpfPixelFormat.dwRGBBitCount,
        desc->dwFlags
    );
}

static void clamp_huge_surface_desc(LPDDSURFACEDESC desc, const char *source)
{
    if (!desc || !env_flag_enabled("PM99_DDRAW_CLAMP_HUGE_SURFACES")) {
        return;
    }
    if (desc->dwWidth <= 10000 && desc->dwHeight <= 10000) {
        return;
    }
    trace_log(
        "%s clamp_huge_surface before width=%lu height=%lu pitch=%ld flags=0x%08lX caps=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->dwFlags,
        desc->ddsCaps.dwCaps,
        desc->ddpfPixelFormat.dwFlags,
        desc->ddpfPixelFormat.dwRGBBitCount
    );
    desc->dwWidth = 640;
    desc->dwHeight = 480;
    desc->lPitch = 0;
    desc->dwFlags |= DDSD_WIDTH | DDSD_HEIGHT;
    trace_log(
        "%s clamp_huge_surface after width=%lu height=%lu pitch=%ld flags=0x%08lX caps=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->dwFlags,
        desc->ddsCaps.dwCaps,
        desc->ddpfPixelFormat.dwFlags,
        desc->ddpfPixelFormat.dwRGBBitCount
    );
}

static void normalize_display_mode_desc2(LPDDSURFACEDESC2 desc, const char *source)
{
    if (!desc || !env_flag_enabled("PM99_DDRAW_NORMALIZE_DISPLAY_MODE")) {
        return;
    }
    trace_log(
        "%s normalize_display_mode before width=%lu height=%lu pitch=%ld rgbbits=%lu flags=0x%08lX",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->ddpfPixelFormat.dwRGBBitCount,
        desc->dwFlags
    );
    desc->dwFlags |= DDSD_WIDTH | DDSD_HEIGHT | DDSD_PITCH | DDSD_PIXELFORMAT;
    desc->dwWidth = 640;
    desc->dwHeight = 480;
    desc->lPitch = 1280;
    desc->ddpfPixelFormat.dwSize = sizeof(DDPIXELFORMAT);
    desc->ddpfPixelFormat.dwFlags = DDPF_RGB;
    desc->ddpfPixelFormat.dwRGBBitCount = 16;
    desc->ddpfPixelFormat.dwRBitMask = 0x0000F800;
    desc->ddpfPixelFormat.dwGBitMask = 0x000007E0;
    desc->ddpfPixelFormat.dwBBitMask = 0x0000001F;
    trace_log(
        "%s normalize_display_mode after width=%lu height=%lu pitch=%ld rgbbits=%lu flags=0x%08lX",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->ddpfPixelFormat.dwRGBBitCount,
        desc->dwFlags
    );
}

static void clamp_huge_surface_desc2(LPDDSURFACEDESC2 desc, const char *source)
{
    if (!desc || !env_flag_enabled("PM99_DDRAW_CLAMP_HUGE_SURFACES")) {
        return;
    }
    if (desc->dwWidth <= 10000 && desc->dwHeight <= 10000) {
        return;
    }
    trace_log(
        "%s clamp_huge_surface before width=%lu height=%lu pitch=%ld flags=0x%08lX caps=0x%08lX caps2=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->dwFlags,
        desc->ddsCaps.dwCaps,
        desc->ddsCaps.dwCaps2,
        desc->ddpfPixelFormat.dwFlags,
        desc->ddpfPixelFormat.dwRGBBitCount
    );
    desc->dwWidth = 640;
    desc->dwHeight = 480;
    desc->lPitch = 0;
    desc->dwFlags |= DDSD_WIDTH | DDSD_HEIGHT;
    trace_log(
        "%s clamp_huge_surface after width=%lu height=%lu pitch=%ld flags=0x%08lX caps=0x%08lX caps2=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        source,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->dwFlags,
        desc->ddsCaps.dwCaps,
        desc->ddsCaps.dwCaps2,
        desc->ddpfPixelFormat.dwFlags,
        desc->ddpfPixelFormat.dwRGBBitCount
    );
}

static void guid_to_text(const GUID *guid, char *out, size_t out_size)
{
    if (!guid) {
        lstrcpynA(out, "NULL", (int)out_size);
        return;
    }
    snprintf(
        out,
        out_size,
        "{%08lX-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}",
        (unsigned long)guid->Data1,
        guid->Data2,
        guid->Data3,
        guid->Data4[0],
        guid->Data4[1],
        guid->Data4[2],
        guid->Data4[3],
        guid->Data4[4],
        guid->Data4[5],
        guid->Data4[6],
        guid->Data4[7]
    );
}

static int ensure_real_ddraw(void)
{
    char system_dir[MAX_PATH];
    char dll_path[MAX_PATH * 2];

    if (real_ddraw_module) {
        return 1;
    }

    if (!GetSystemDirectoryA(system_dir, sizeof(system_dir))) {
        trace_log("load_real_ddraw GetSystemDirectoryA failed last_error=0x%08lX", GetLastError());
        return 0;
    }

    snprintf(dll_path, sizeof(dll_path), "%s\\ddraw.dll", system_dir);
    real_ddraw_module = LoadLibraryA(dll_path);
    if (!real_ddraw_module) {
        trace_log("load_real_ddraw LoadLibraryA path=%s failed last_error=0x%08lX", dll_path, GetLastError());
        return 0;
    }

    real_DirectDrawCreate = (PFN_DirectDrawCreate)GetProcAddress(real_ddraw_module, "DirectDrawCreate");
    real_DirectDrawCreateEx = (PFN_DirectDrawCreateEx)GetProcAddress(real_ddraw_module, "DirectDrawCreateEx");
    real_DirectDrawEnumerateA = (PFN_DirectDrawEnumerateA)GetProcAddress(real_ddraw_module, "DirectDrawEnumerateA");
    real_DirectDrawEnumerateExA = (PFN_DirectDrawEnumerateExA)GetProcAddress(real_ddraw_module, "DirectDrawEnumerateExA");

    trace_log(
        "load_real_ddraw path=%s create=%p create_ex=%p enum_a=%p enum_ex_a=%p",
        dll_path,
        real_DirectDrawCreate,
        real_DirectDrawCreateEx,
        real_DirectDrawEnumerateA,
        real_DirectDrawEnumerateExA
    );

    return real_DirectDrawCreate && real_DirectDrawEnumerateA;
}

static TraceDirectDraw *trace_from_iface(LPDIRECTDRAW iface)
{
    return (TraceDirectDraw *)iface;
}

static TraceDirectDraw4 *trace4_from_iface(LPDIRECTDRAW4 iface)
{
    return (TraceDirectDraw4 *)iface;
}

static HRESULT wrap_directdraw4(LPDIRECTDRAW4 real, LPVOID *out);

static void log_surface_desc(const char *prefix, LPDDSURFACEDESC desc)
{
    if (!desc) {
        trace_log("%s desc=NULL", prefix);
        return;
    }

    trace_log(
        "%s size=%lu flags=0x%08lX width=%lu height=%lu pitch=%ld backbuffers=%lu caps=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        prefix,
        desc->dwSize,
        desc->dwFlags,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->dwBackBufferCount,
        desc->ddsCaps.dwCaps,
        desc->ddpfPixelFormat.dwFlags,
        desc->ddpfPixelFormat.dwRGBBitCount
    );
}

static void log_surface_desc2(const char *prefix, LPDDSURFACEDESC2 desc)
{
    if (!desc) {
        trace_log("%s desc=NULL", prefix);
        return;
    }

    trace_log(
        "%s size=%lu flags=0x%08lX width=%lu height=%lu pitch=%ld backbuffers=%lu caps=0x%08lX caps2=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        prefix,
        desc->dwSize,
        desc->dwFlags,
        desc->dwWidth,
        desc->dwHeight,
        desc->lPitch,
        desc->dwBackBufferCount,
        desc->ddsCaps.dwCaps,
        desc->ddsCaps.dwCaps2,
        desc->ddpfPixelFormat.dwFlags,
        desc->ddpfPixelFormat.dwRGBBitCount
    );
}

static HRESULT WINAPI trace_enum_display_mode_callback(LPDDSURFACEDESC desc, LPVOID context)
{
    EnumModesContext *ctx = (EnumModesContext *)context;
    HRESULT callback_result;

    ctx->seen++;
    trace_log(
        "%s callback mode #%lu width=%lu height=%lu pitch=%ld flags=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        ctx->source,
        ctx->seen,
        desc ? desc->dwWidth : 0,
        desc ? desc->dwHeight : 0,
        desc ? desc->lPitch : 0,
        desc ? desc->dwFlags : 0,
        desc ? desc->ddpfPixelFormat.dwFlags : 0,
        desc ? desc->ddpfPixelFormat.dwRGBBitCount : 0
    );

    if (enum_mode_filter_enabled() && !mode_desc_matches_640x480x16(desc)) {
        ctx->filtered++;
        trace_log("%s callback mode #%lu filtered", ctx->source, ctx->seen);
        return DDENUMRET_OK;
    }

    ctx->passed++;
    callback_result = ctx->callback(desc, ctx->context);
    trace_log("%s callback mode #%lu game_result=0x%08lX", ctx->source, ctx->seen, (unsigned long)callback_result);
    return callback_result;
}

static HRESULT WINAPI trace_enum_display_mode2_callback(LPDDSURFACEDESC2 desc, LPVOID context)
{
    EnumModes2Context *ctx = (EnumModes2Context *)context;
    HRESULT callback_result;

    ctx->seen++;
    trace_log(
        "%s callback mode #%lu width=%lu height=%lu pitch=%ld flags=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        ctx->source,
        ctx->seen,
        desc ? desc->dwWidth : 0,
        desc ? desc->dwHeight : 0,
        desc ? desc->lPitch : 0,
        desc ? desc->dwFlags : 0,
        desc ? desc->ddpfPixelFormat.dwFlags : 0,
        desc ? desc->ddpfPixelFormat.dwRGBBitCount : 0
    );

    if (enum_mode_filter_enabled() && !mode_desc2_matches_640x480x16(desc)) {
        ctx->filtered++;
        trace_log("%s callback mode #%lu filtered", ctx->source, ctx->seen);
        return DDENUMRET_OK;
    }

    ctx->passed++;
    callback_result = ctx->callback(desc, ctx->context);
    trace_log("%s callback mode #%lu game_result=0x%08lX", ctx->source, ctx->seen, (unsigned long)callback_result);
    return callback_result;
}

static void inject_synthetic_enum_mode_if_needed(EnumModesContext *ctx)
{
    DDSURFACEDESC synthetic_desc;
    HRESULT callback_result;

    if (!enum_mode_injection_enabled() || !ctx || ctx->passed != 0) {
        return;
    }

    fill_synthetic_640x480x16_desc(&synthetic_desc);
    ctx->seen++;
    ctx->passed++;
    trace_log(
        "%s callback mode #%lu synthetic width=%lu height=%lu pitch=%ld flags=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        ctx->source,
        ctx->seen,
        synthetic_desc.dwWidth,
        synthetic_desc.dwHeight,
        synthetic_desc.lPitch,
        synthetic_desc.dwFlags,
        synthetic_desc.ddpfPixelFormat.dwFlags,
        synthetic_desc.ddpfPixelFormat.dwRGBBitCount
    );
    callback_result = ctx->callback(&synthetic_desc, ctx->context);
    trace_log("%s callback synthetic game_result=0x%08lX", ctx->source, (unsigned long)callback_result);
}

static void inject_synthetic_enum_mode2_if_needed(EnumModes2Context *ctx)
{
    DDSURFACEDESC2 synthetic_desc;
    HRESULT callback_result;

    if (!enum_mode_injection_enabled() || !ctx || ctx->passed != 0) {
        return;
    }

    fill_synthetic_640x480x16_desc2(&synthetic_desc);
    ctx->seen++;
    ctx->passed++;
    trace_log(
        "%s callback mode #%lu synthetic width=%lu height=%lu pitch=%ld flags=0x%08lX pixelflags=0x%08lX rgbbits=%lu",
        ctx->source,
        ctx->seen,
        synthetic_desc.dwWidth,
        synthetic_desc.dwHeight,
        synthetic_desc.lPitch,
        synthetic_desc.dwFlags,
        synthetic_desc.ddpfPixelFormat.dwFlags,
        synthetic_desc.ddpfPixelFormat.dwRGBBitCount
    );
    callback_result = ctx->callback(&synthetic_desc, ctx->context);
    trace_log("%s callback synthetic game_result=0x%08lX", ctx->source, (unsigned long)callback_result);
}

static HRESULT WINAPI trace_ddraw_QueryInterface(LPDIRECTDRAW iface, REFIID riid, LPVOID *out)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    char riid_text[64];
    HRESULT hr;

    guid_to_text(riid, riid_text, sizeof(riid_text));
    hr = self->real->lpVtbl->QueryInterface(self->real, riid, out);
    trace_log("IDirectDraw::QueryInterface riid=%s hr=0x%08lX %s out=%p", riid_text, (unsigned long)hr, hr_state(hr), out ? *out : NULL);
    if (SUCCEEDED(hr) && out && *out && IsEqualGUID(riid, &PM99_IID_IDirectDraw4)) {
        hr = wrap_directdraw4((LPDIRECTDRAW4)*out, out);
        trace_log("IDirectDraw::QueryInterface wrapped IDirectDraw4 hr=0x%08lX %s out=%p", (unsigned long)hr, hr_state(hr), out ? *out : NULL);
    }
    return hr;
}

static ULONG WINAPI trace_ddraw_AddRef(LPDIRECTDRAW iface)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    ULONG real_refs = self->real->lpVtbl->AddRef(self->real);
    LONG refs = InterlockedIncrement(&self->refs);
    trace_log("IDirectDraw::AddRef wrapper_refs=%ld real_refs=%lu", refs, real_refs);
    return (ULONG)refs;
}

static ULONG WINAPI trace_ddraw_Release(LPDIRECTDRAW iface)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    ULONG real_refs = self->real->lpVtbl->Release(self->real);
    LONG refs = InterlockedDecrement(&self->refs);
    trace_log("IDirectDraw::Release wrapper_refs=%ld real_refs=%lu", refs, real_refs);
    if (refs <= 0) {
        HeapFree(GetProcessHeap(), 0, self);
        return 0;
    }
    return (ULONG)refs;
}

static HRESULT WINAPI trace_ddraw_Compact(LPDIRECTDRAW iface)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->Compact(self->real);
    trace_log("IDirectDraw::Compact hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_CreateClipper(LPDIRECTDRAW iface, DWORD flags, LPDIRECTDRAWCLIPPER *clipper, IUnknown *outer)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->CreateClipper(self->real, flags, clipper, outer);
    trace_log("IDirectDraw::CreateClipper flags=0x%08lX hr=0x%08lX %s clipper=%p", flags, (unsigned long)hr, hr_state(hr), clipper ? *clipper : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw_CreatePalette(LPDIRECTDRAW iface, DWORD flags, LPPALETTEENTRY entries, LPDIRECTDRAWPALETTE *palette, IUnknown *outer)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->CreatePalette(self->real, flags, entries, palette, outer);
    trace_log("IDirectDraw::CreatePalette flags=0x%08lX entries=%p hr=0x%08lX %s palette=%p", flags, entries, (unsigned long)hr, hr_state(hr), palette ? *palette : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw_CreateSurface(LPDIRECTDRAW iface, LPDDSURFACEDESC desc, LPDIRECTDRAWSURFACE *surface, IUnknown *outer)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr;
    log_surface_desc("IDirectDraw::CreateSurface input", desc);
    clamp_huge_surface_desc(desc, "IDirectDraw::CreateSurface");
    hr = self->real->lpVtbl->CreateSurface(self->real, desc, surface, outer);
    trace_log("IDirectDraw::CreateSurface hr=0x%08lX %s surface=%p", (unsigned long)hr, hr_state(hr), surface ? *surface : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw_DuplicateSurface(LPDIRECTDRAW iface, LPDIRECTDRAWSURFACE source, LPDIRECTDRAWSURFACE *target)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->DuplicateSurface(self->real, source, target);
    trace_log("IDirectDraw::DuplicateSurface source=%p hr=0x%08lX %s target=%p", source, (unsigned long)hr, hr_state(hr), target ? *target : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw_EnumDisplayModes(LPDIRECTDRAW iface, DWORD flags, LPDDSURFACEDESC desc, LPVOID context, LPDDENUMMODESCALLBACK callback)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    EnumModesContext wrapped_context;
    HRESULT hr;
    log_surface_desc("IDirectDraw::EnumDisplayModes filter", desc);
    if (callback) {
        ZeroMemory(&wrapped_context, sizeof(wrapped_context));
        wrapped_context.callback = callback;
        wrapped_context.context = context;
        wrapped_context.source = "IDirectDraw::EnumDisplayModes";
        hr = self->real->lpVtbl->EnumDisplayModes(self->real, flags, desc, &wrapped_context, trace_enum_display_mode_callback);
        if (SUCCEEDED(hr)) {
            inject_synthetic_enum_mode_if_needed(&wrapped_context);
        }
        trace_log(
            "IDirectDraw::EnumDisplayModes flags=0x%08lX callback=%p seen=%lu passed=%lu filtered=%lu hr=0x%08lX %s",
            flags,
            callback,
            wrapped_context.seen,
            wrapped_context.passed,
            wrapped_context.filtered,
            (unsigned long)hr,
            hr_state(hr)
        );
    } else {
        hr = self->real->lpVtbl->EnumDisplayModes(self->real, flags, desc, context, callback);
        trace_log("IDirectDraw::EnumDisplayModes flags=0x%08lX callback=NULL hr=0x%08lX %s", flags, (unsigned long)hr, hr_state(hr));
    }
    return hr;
}

static HRESULT WINAPI trace_ddraw_EnumSurfaces(LPDIRECTDRAW iface, DWORD flags, LPDDSURFACEDESC desc, LPVOID context, LPDDENUMSURFACESCALLBACK callback)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr;
    log_surface_desc("IDirectDraw::EnumSurfaces filter", desc);
    hr = self->real->lpVtbl->EnumSurfaces(self->real, flags, desc, context, callback);
    trace_log("IDirectDraw::EnumSurfaces flags=0x%08lX callback=%p hr=0x%08lX %s", flags, callback, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_FlipToGDISurface(LPDIRECTDRAW iface)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->FlipToGDISurface(self->real);
    trace_log("IDirectDraw::FlipToGDISurface hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_GetCaps(LPDIRECTDRAW iface, LPDDCAPS driver_caps, LPDDCAPS hel_caps)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetCaps(self->real, driver_caps, hel_caps);
    trace_log("IDirectDraw::GetCaps hr=0x%08lX %s driver=%p hel=%p", (unsigned long)hr, hr_state(hr), driver_caps, hel_caps);
    return hr;
}

static HRESULT WINAPI trace_ddraw_GetDisplayMode(LPDIRECTDRAW iface, LPDDSURFACEDESC desc)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetDisplayMode(self->real, desc);
    trace_log("IDirectDraw::GetDisplayMode hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    if (SUCCEEDED(hr)) {
        normalize_display_mode_desc(desc, "IDirectDraw::GetDisplayMode");
    }
    log_surface_desc("IDirectDraw::GetDisplayMode output", SUCCEEDED(hr) ? desc : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw_GetFourCCCodes(LPDIRECTDRAW iface, LPDWORD count, LPDWORD codes)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetFourCCCodes(self->real, count, codes);
    trace_log("IDirectDraw::GetFourCCCodes count=%lu hr=0x%08lX %s", count ? *count : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_GetGDISurface(LPDIRECTDRAW iface, LPDIRECTDRAWSURFACE *surface)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetGDISurface(self->real, surface);
    trace_log("IDirectDraw::GetGDISurface hr=0x%08lX %s surface=%p", (unsigned long)hr, hr_state(hr), surface ? *surface : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw_GetMonitorFrequency(LPDIRECTDRAW iface, LPDWORD frequency)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetMonitorFrequency(self->real, frequency);
    trace_log("IDirectDraw::GetMonitorFrequency frequency=%lu hr=0x%08lX %s", frequency ? *frequency : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_GetScanLine(LPDIRECTDRAW iface, LPDWORD scanline)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetScanLine(self->real, scanline);
    trace_log("IDirectDraw::GetScanLine scanline=%lu hr=0x%08lX %s", scanline ? *scanline : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_GetVerticalBlankStatus(LPDIRECTDRAW iface, LPBOOL status)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetVerticalBlankStatus(self->real, status);
    trace_log("IDirectDraw::GetVerticalBlankStatus status=%d hr=0x%08lX %s", status ? *status : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_Initialize(LPDIRECTDRAW iface, GUID *guid)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    char guid_text[64];
    HRESULT hr;
    guid_to_text(guid, guid_text, sizeof(guid_text));
    hr = self->real->lpVtbl->Initialize(self->real, guid);
    trace_log("IDirectDraw::Initialize guid=%s hr=0x%08lX %s", guid_text, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_RestoreDisplayMode(LPDIRECTDRAW iface)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->RestoreDisplayMode(self->real);
    trace_log("IDirectDraw::RestoreDisplayMode hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_SetCooperativeLevel(LPDIRECTDRAW iface, HWND hwnd, DWORD flags)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->SetCooperativeLevel(self->real, hwnd, flags);
    trace_log("IDirectDraw::SetCooperativeLevel hwnd=%p flags=0x%08lX hr=0x%08lX %s", hwnd, flags, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw_SetDisplayMode(LPDIRECTDRAW iface, DWORD width, DWORD height, DWORD bpp)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->SetDisplayMode(self->real, width, height, bpp);
    trace_log("IDirectDraw::SetDisplayMode width=%lu height=%lu bpp=%lu hr=0x%08lX %s", width, height, bpp, (unsigned long)hr, hr_state(hr));
    hr = maybe_force_set_display_mode_ok(hr, width, height, bpp, "IDirectDraw::SetDisplayMode");
    return hr;
}

static HRESULT WINAPI trace_ddraw_WaitForVerticalBlank(LPDIRECTDRAW iface, DWORD flags, HANDLE event)
{
    TraceDirectDraw *self = trace_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->WaitForVerticalBlank(self->real, flags, event);
    trace_log("IDirectDraw::WaitForVerticalBlank flags=0x%08lX event=%p hr=0x%08lX %s", flags, event, (unsigned long)hr, hr_state(hr));
    return hr;
}

static IDirectDrawVtbl trace_ddraw_vtbl = {
    trace_ddraw_QueryInterface,
    trace_ddraw_AddRef,
    trace_ddraw_Release,
    trace_ddraw_Compact,
    trace_ddraw_CreateClipper,
    trace_ddraw_CreatePalette,
    trace_ddraw_CreateSurface,
    trace_ddraw_DuplicateSurface,
    trace_ddraw_EnumDisplayModes,
    trace_ddraw_EnumSurfaces,
    trace_ddraw_FlipToGDISurface,
    trace_ddraw_GetCaps,
    trace_ddraw_GetDisplayMode,
    trace_ddraw_GetFourCCCodes,
    trace_ddraw_GetGDISurface,
    trace_ddraw_GetMonitorFrequency,
    trace_ddraw_GetScanLine,
    trace_ddraw_GetVerticalBlankStatus,
    trace_ddraw_Initialize,
    trace_ddraw_RestoreDisplayMode,
    trace_ddraw_SetCooperativeLevel,
    trace_ddraw_SetDisplayMode,
    trace_ddraw_WaitForVerticalBlank
};

static HRESULT WINAPI trace_ddraw4_QueryInterface(LPDIRECTDRAW4 iface, REFIID riid, LPVOID *out)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    char riid_text[64];
    HRESULT hr;

    guid_to_text(riid, riid_text, sizeof(riid_text));
    hr = self->real->lpVtbl->QueryInterface(self->real, riid, out);
    trace_log("IDirectDraw4::QueryInterface riid=%s hr=0x%08lX %s out=%p", riid_text, (unsigned long)hr, hr_state(hr), out ? *out : NULL);
    if (SUCCEEDED(hr) && out && *out && IsEqualGUID(riid, &PM99_IID_IDirectDraw4)) {
        hr = wrap_directdraw4((LPDIRECTDRAW4)*out, out);
        trace_log("IDirectDraw4::QueryInterface wrapped IDirectDraw4 hr=0x%08lX %s out=%p", (unsigned long)hr, hr_state(hr), out ? *out : NULL);
    }
    return hr;
}

static ULONG WINAPI trace_ddraw4_AddRef(LPDIRECTDRAW4 iface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    ULONG real_refs = self->real->lpVtbl->AddRef(self->real);
    LONG refs = InterlockedIncrement(&self->refs);
    trace_log("IDirectDraw4::AddRef wrapper_refs=%ld real_refs=%lu", refs, real_refs);
    return (ULONG)refs;
}

static ULONG WINAPI trace_ddraw4_Release(LPDIRECTDRAW4 iface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    ULONG real_refs = self->real->lpVtbl->Release(self->real);
    LONG refs = InterlockedDecrement(&self->refs);
    trace_log("IDirectDraw4::Release wrapper_refs=%ld real_refs=%lu", refs, real_refs);
    if (refs <= 0) {
        HeapFree(GetProcessHeap(), 0, self);
        return 0;
    }
    return (ULONG)refs;
}

static HRESULT WINAPI trace_ddraw4_Compact(LPDIRECTDRAW4 iface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->Compact(self->real);
    trace_log("IDirectDraw4::Compact hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_CreateClipper(LPDIRECTDRAW4 iface, DWORD flags, LPDIRECTDRAWCLIPPER *clipper, IUnknown *outer)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->CreateClipper(self->real, flags, clipper, outer);
    trace_log("IDirectDraw4::CreateClipper flags=0x%08lX hr=0x%08lX %s clipper=%p", flags, (unsigned long)hr, hr_state(hr), clipper ? *clipper : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_CreatePalette(LPDIRECTDRAW4 iface, DWORD flags, LPPALETTEENTRY entries, LPDIRECTDRAWPALETTE *palette, IUnknown *outer)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->CreatePalette(self->real, flags, entries, palette, outer);
    trace_log("IDirectDraw4::CreatePalette flags=0x%08lX entries=%p hr=0x%08lX %s palette=%p", flags, entries, (unsigned long)hr, hr_state(hr), palette ? *palette : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_CreateSurface(LPDIRECTDRAW4 iface, LPDDSURFACEDESC2 desc, LPDIRECTDRAWSURFACE4 *surface, IUnknown *outer)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr;
    log_surface_desc2("IDirectDraw4::CreateSurface input", desc);
    clamp_huge_surface_desc2(desc, "IDirectDraw4::CreateSurface");
    hr = self->real->lpVtbl->CreateSurface(self->real, desc, surface, outer);
    trace_log("IDirectDraw4::CreateSurface hr=0x%08lX %s surface=%p", (unsigned long)hr, hr_state(hr), surface ? *surface : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_DuplicateSurface(LPDIRECTDRAW4 iface, LPDIRECTDRAWSURFACE4 source, LPDIRECTDRAWSURFACE4 *target)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->DuplicateSurface(self->real, source, target);
    trace_log("IDirectDraw4::DuplicateSurface source=%p hr=0x%08lX %s target=%p", source, (unsigned long)hr, hr_state(hr), target ? *target : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_EnumDisplayModes(LPDIRECTDRAW4 iface, DWORD flags, LPDDSURFACEDESC2 desc, LPVOID context, LPDDENUMMODESCALLBACK2 callback)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    EnumModes2Context wrapped_context;
    HRESULT hr;
    log_surface_desc2("IDirectDraw4::EnumDisplayModes filter", desc);
    if (callback) {
        ZeroMemory(&wrapped_context, sizeof(wrapped_context));
        wrapped_context.callback = callback;
        wrapped_context.context = context;
        wrapped_context.source = "IDirectDraw4::EnumDisplayModes";
        hr = self->real->lpVtbl->EnumDisplayModes(self->real, flags, desc, &wrapped_context, trace_enum_display_mode2_callback);
        if (SUCCEEDED(hr)) {
            inject_synthetic_enum_mode2_if_needed(&wrapped_context);
        }
        trace_log(
            "IDirectDraw4::EnumDisplayModes flags=0x%08lX callback=%p seen=%lu passed=%lu filtered=%lu hr=0x%08lX %s",
            flags,
            callback,
            wrapped_context.seen,
            wrapped_context.passed,
            wrapped_context.filtered,
            (unsigned long)hr,
            hr_state(hr)
        );
    } else {
        hr = self->real->lpVtbl->EnumDisplayModes(self->real, flags, desc, context, callback);
        trace_log("IDirectDraw4::EnumDisplayModes flags=0x%08lX callback=NULL hr=0x%08lX %s", flags, (unsigned long)hr, hr_state(hr));
    }
    return hr;
}

static HRESULT WINAPI trace_ddraw4_EnumSurfaces(LPDIRECTDRAW4 iface, DWORD flags, LPDDSURFACEDESC2 desc, LPVOID context, LPDDENUMSURFACESCALLBACK2 callback)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr;
    log_surface_desc2("IDirectDraw4::EnumSurfaces filter", desc);
    hr = self->real->lpVtbl->EnumSurfaces(self->real, flags, desc, context, callback);
    trace_log("IDirectDraw4::EnumSurfaces flags=0x%08lX callback=%p hr=0x%08lX %s", flags, callback, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_FlipToGDISurface(LPDIRECTDRAW4 iface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->FlipToGDISurface(self->real);
    trace_log("IDirectDraw4::FlipToGDISurface hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetCaps(LPDIRECTDRAW4 iface, LPDDCAPS driver_caps, LPDDCAPS hel_caps)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetCaps(self->real, driver_caps, hel_caps);
    trace_log("IDirectDraw4::GetCaps hr=0x%08lX %s driver=%p hel=%p", (unsigned long)hr, hr_state(hr), driver_caps, hel_caps);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetDisplayMode(LPDIRECTDRAW4 iface, LPDDSURFACEDESC2 desc)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetDisplayMode(self->real, desc);
    trace_log("IDirectDraw4::GetDisplayMode hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    if (SUCCEEDED(hr)) {
        normalize_display_mode_desc2(desc, "IDirectDraw4::GetDisplayMode");
    }
    log_surface_desc2("IDirectDraw4::GetDisplayMode output", SUCCEEDED(hr) ? desc : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetFourCCCodes(LPDIRECTDRAW4 iface, LPDWORD count, LPDWORD codes)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetFourCCCodes(self->real, count, codes);
    trace_log("IDirectDraw4::GetFourCCCodes count=%lu hr=0x%08lX %s", count ? *count : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetGDISurface(LPDIRECTDRAW4 iface, LPDIRECTDRAWSURFACE4 *surface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetGDISurface(self->real, surface);
    trace_log("IDirectDraw4::GetGDISurface hr=0x%08lX %s surface=%p", (unsigned long)hr, hr_state(hr), surface ? *surface : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetMonitorFrequency(LPDIRECTDRAW4 iface, LPDWORD frequency)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetMonitorFrequency(self->real, frequency);
    trace_log("IDirectDraw4::GetMonitorFrequency frequency=%lu hr=0x%08lX %s", frequency ? *frequency : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetScanLine(LPDIRECTDRAW4 iface, LPDWORD scanline)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetScanLine(self->real, scanline);
    trace_log("IDirectDraw4::GetScanLine scanline=%lu hr=0x%08lX %s", scanline ? *scanline : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetVerticalBlankStatus(LPDIRECTDRAW4 iface, LPBOOL status)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetVerticalBlankStatus(self->real, status);
    trace_log("IDirectDraw4::GetVerticalBlankStatus status=%d hr=0x%08lX %s", status ? *status : 0, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_Initialize(LPDIRECTDRAW4 iface, GUID *guid)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    char guid_text[64];
    HRESULT hr;
    guid_to_text(guid, guid_text, sizeof(guid_text));
    hr = self->real->lpVtbl->Initialize(self->real, guid);
    trace_log("IDirectDraw4::Initialize guid=%s hr=0x%08lX %s", guid_text, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_RestoreDisplayMode(LPDIRECTDRAW4 iface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->RestoreDisplayMode(self->real);
    trace_log("IDirectDraw4::RestoreDisplayMode hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_SetCooperativeLevel(LPDIRECTDRAW4 iface, HWND hwnd, DWORD flags)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->SetCooperativeLevel(self->real, hwnd, flags);
    trace_log("IDirectDraw4::SetCooperativeLevel hwnd=%p flags=0x%08lX hr=0x%08lX %s", hwnd, flags, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_SetDisplayMode(LPDIRECTDRAW4 iface, DWORD width, DWORD height, DWORD bpp, DWORD refresh, DWORD flags)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->SetDisplayMode(self->real, width, height, bpp, refresh, flags);
    trace_log("IDirectDraw4::SetDisplayMode width=%lu height=%lu bpp=%lu refresh=%lu flags=0x%08lX hr=0x%08lX %s", width, height, bpp, refresh, flags, (unsigned long)hr, hr_state(hr));
    hr = maybe_force_set_display_mode_ok(hr, width, height, bpp, "IDirectDraw4::SetDisplayMode");
    return hr;
}

static HRESULT WINAPI trace_ddraw4_WaitForVerticalBlank(LPDIRECTDRAW4 iface, DWORD flags, HANDLE event)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->WaitForVerticalBlank(self->real, flags, event);
    trace_log("IDirectDraw4::WaitForVerticalBlank flags=0x%08lX event=%p hr=0x%08lX %s", flags, event, (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetAvailableVidMem(LPDIRECTDRAW4 iface, LPDDSCAPS2 caps, LPDWORD total, LPDWORD free_mem)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetAvailableVidMem(self->real, caps, total, free_mem);
    trace_log(
        "IDirectDraw4::GetAvailableVidMem caps=0x%08lX caps2=0x%08lX total=%lu free=%lu hr=0x%08lX %s",
        caps ? caps->dwCaps : 0,
        caps ? caps->dwCaps2 : 0,
        total ? *total : 0,
        free_mem ? *free_mem : 0,
        (unsigned long)hr,
        hr_state(hr)
    );
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetSurfaceFromDC(LPDIRECTDRAW4 iface, HDC dc, LPDIRECTDRAWSURFACE4 *surface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetSurfaceFromDC(self->real, dc, surface);
    trace_log("IDirectDraw4::GetSurfaceFromDC dc=%p hr=0x%08lX %s surface=%p", dc, (unsigned long)hr, hr_state(hr), surface ? *surface : NULL);
    return hr;
}

static HRESULT WINAPI trace_ddraw4_RestoreAllSurfaces(LPDIRECTDRAW4 iface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->RestoreAllSurfaces(self->real);
    trace_log("IDirectDraw4::RestoreAllSurfaces hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_TestCooperativeLevel(LPDIRECTDRAW4 iface)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->TestCooperativeLevel(self->real);
    trace_log("IDirectDraw4::TestCooperativeLevel hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

static HRESULT WINAPI trace_ddraw4_GetDeviceIdentifier(LPDIRECTDRAW4 iface, LPDDDEVICEIDENTIFIER identifier, DWORD flags)
{
    TraceDirectDraw4 *self = trace4_from_iface(iface);
    HRESULT hr = self->real->lpVtbl->GetDeviceIdentifier(self->real, identifier, flags);
    trace_log("IDirectDraw4::GetDeviceIdentifier flags=0x%08lX hr=0x%08lX %s", flags, (unsigned long)hr, hr_state(hr));
    return hr;
}

static IDirectDraw4Vtbl trace_ddraw4_vtbl = {
    trace_ddraw4_QueryInterface,
    trace_ddraw4_AddRef,
    trace_ddraw4_Release,
    trace_ddraw4_Compact,
    trace_ddraw4_CreateClipper,
    trace_ddraw4_CreatePalette,
    trace_ddraw4_CreateSurface,
    trace_ddraw4_DuplicateSurface,
    trace_ddraw4_EnumDisplayModes,
    trace_ddraw4_EnumSurfaces,
    trace_ddraw4_FlipToGDISurface,
    trace_ddraw4_GetCaps,
    trace_ddraw4_GetDisplayMode,
    trace_ddraw4_GetFourCCCodes,
    trace_ddraw4_GetGDISurface,
    trace_ddraw4_GetMonitorFrequency,
    trace_ddraw4_GetScanLine,
    trace_ddraw4_GetVerticalBlankStatus,
    trace_ddraw4_Initialize,
    trace_ddraw4_RestoreDisplayMode,
    trace_ddraw4_SetCooperativeLevel,
    trace_ddraw4_SetDisplayMode,
    trace_ddraw4_WaitForVerticalBlank,
    trace_ddraw4_GetAvailableVidMem,
    trace_ddraw4_GetSurfaceFromDC,
    trace_ddraw4_RestoreAllSurfaces,
    trace_ddraw4_TestCooperativeLevel,
    trace_ddraw4_GetDeviceIdentifier
};

static HRESULT wrap_directdraw(LPDIRECTDRAW real, LPDIRECTDRAW *out)
{
    TraceDirectDraw *wrapped;

    if (!real || !out) {
        return DDERR_INVALIDPARAMS;
    }

    wrapped = (TraceDirectDraw *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*wrapped));
    if (!wrapped) {
        real->lpVtbl->Release(real);
        return E_OUTOFMEMORY;
    }

    wrapped->iface.lpVtbl = &trace_ddraw_vtbl;
    wrapped->real = real;
    wrapped->refs = 1;
    *out = &wrapped->iface;
    trace_log("wrap IDirectDraw real=%p wrapper=%p", real, *out);
    return DD_OK;
}

static HRESULT wrap_directdraw4(LPDIRECTDRAW4 real, LPVOID *out)
{
    TraceDirectDraw4 *wrapped;

    if (!real || !out) {
        return DDERR_INVALIDPARAMS;
    }

    wrapped = (TraceDirectDraw4 *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*wrapped));
    if (!wrapped) {
        real->lpVtbl->Release(real);
        *out = NULL;
        return E_OUTOFMEMORY;
    }

    wrapped->iface.lpVtbl = &trace_ddraw4_vtbl;
    wrapped->real = real;
    wrapped->refs = 1;
    *out = &wrapped->iface;
    trace_log("wrap IDirectDraw4 real=%p wrapper=%p", real, *out);
    return DD_OK;
}

typedef struct EnumAContext {
    LPDDENUMCALLBACKA callback;
    LPVOID context;
} EnumAContext;

static BOOL WINAPI trace_enum_a_callback(GUID *guid, LPSTR description, LPSTR name, LPVOID context)
{
    EnumAContext *ctx = (EnumAContext *)context;
    char guid_text[64];
    BOOL keep_going;

    guid_to_text(guid, guid_text, sizeof(guid_text));
    trace_log("DirectDrawEnumerateA device guid=%s description=\"%s\" name=\"%s\"", guid_text, description ? description : "", name ? name : "");
    keep_going = ctx->callback(guid, description, name, ctx->context);
    trace_log("DirectDrawEnumerateA callback result=%d", keep_going);
    return keep_going;
}

HRESULT WINAPI DirectDrawCreate(GUID *guid, LPDIRECTDRAW *out, IUnknown *outer)
{
    LPDIRECTDRAW real = NULL;
    char guid_text[64];
    HRESULT hr;

    guid_to_text(guid, guid_text, sizeof(guid_text));
    trace_log("DirectDrawCreate enter guid=%s out=%p outer=%p", guid_text, out, outer);

    if (!ensure_real_ddraw()) {
        return DDERR_GENERIC;
    }

    hr = real_DirectDrawCreate(guid, &real, outer);
    trace_log("DirectDrawCreate real hr=0x%08lX %s real=%p", (unsigned long)hr, hr_state(hr), real);
    if (FAILED(hr)) {
        if (out) {
            *out = NULL;
        }
        return hr;
    }

    hr = wrap_directdraw(real, out);
    trace_log("DirectDrawCreate wrap hr=0x%08lX %s out=%p", (unsigned long)hr, hr_state(hr), out ? *out : NULL);
    return hr;
}

HRESULT WINAPI DirectDrawCreateEx(GUID *guid, LPVOID *out, REFIID iid, IUnknown *outer)
{
    char guid_text[64];
    char iid_text[64];
    HRESULT hr;

    guid_to_text(guid, guid_text, sizeof(guid_text));
    guid_to_text(iid, iid_text, sizeof(iid_text));
    trace_log("DirectDrawCreateEx enter guid=%s iid=%s out=%p outer=%p", guid_text, iid_text, out, outer);

    if (!ensure_real_ddraw() || !real_DirectDrawCreateEx) {
        return DDERR_UNSUPPORTED;
    }

    hr = real_DirectDrawCreateEx(guid, out, iid, outer);
    trace_log("DirectDrawCreateEx hr=0x%08lX %s out=%p", (unsigned long)hr, hr_state(hr), out ? *out : NULL);
    if (SUCCEEDED(hr) && out && *out && IsEqualGUID(iid, &PM99_IID_IDirectDraw4)) {
        hr = wrap_directdraw4((LPDIRECTDRAW4)*out, out);
        trace_log("DirectDrawCreateEx wrapped IDirectDraw4 hr=0x%08lX %s out=%p", (unsigned long)hr, hr_state(hr), out ? *out : NULL);
    }
    return hr;
}

HRESULT WINAPI DirectDrawEnumerateA(LPDDENUMCALLBACKA callback, LPVOID context)
{
    EnumAContext wrapped_context;
    HRESULT hr;

    trace_log("DirectDrawEnumerateA enter callback=%p context=%p", callback, context);
    if (!ensure_real_ddraw()) {
        return DDERR_GENERIC;
    }
    if (!callback) {
        return real_DirectDrawEnumerateA(callback, context);
    }

    wrapped_context.callback = callback;
    wrapped_context.context = context;
    hr = real_DirectDrawEnumerateA(trace_enum_a_callback, &wrapped_context);
    trace_log("DirectDrawEnumerateA hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

HRESULT WINAPI DirectDrawEnumerateExA(LPDDENUMCALLBACKEXA callback, LPVOID context, DWORD flags)
{
    HRESULT hr;

    trace_log("DirectDrawEnumerateExA enter callback=%p context=%p flags=0x%08lX", callback, context, flags);
    if (!ensure_real_ddraw() || !real_DirectDrawEnumerateExA) {
        return DDERR_UNSUPPORTED;
    }

    hr = real_DirectDrawEnumerateExA(callback, context, flags);
    trace_log("DirectDrawEnumerateExA hr=0x%08lX %s", (unsigned long)hr, hr_state(hr));
    return hr;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)instance;
    (void)reserved;

    if (reason == DLL_PROCESS_ATTACH) {
        trace_log("pm99 ddraw trace proxy attached");
    } else if (reason == DLL_PROCESS_DETACH) {
        trace_log("pm99 ddraw trace proxy detached");
        if (real_ddraw_module) {
            FreeLibrary(real_ddraw_module);
            real_ddraw_module = NULL;
        }
    }
    return TRUE;
}
