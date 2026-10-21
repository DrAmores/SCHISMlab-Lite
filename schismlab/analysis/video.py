"""Vídeos MP4 de un campo en planta o en una sección (explorador de Resultados)."""
from __future__ import annotations
import glob
import logging
from pathlib import Path
from types import SimpleNamespace
import numpy as np

log = logging.getLogger(__name__)


def _writer(fps: int):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.animation import FFMpegWriter
    return FFMpegWriter(fps=fps, bitrate=6000, codec="libx264", extra_args=["-pix_fmt", "yuv420p"])


def field_video(ds, var: str, out, layer: int = -1, depth_m: float | None = None, vg=None, arrows: bool = False, fps: int = 8,
                step: int = 1, progress=None, lang: str = "es", n: int = 300, land: list | None = None):
    """MP4 del mapa de `var` (capa o profundidad fija) con flechas opcionales, escala de color fija; `land`: polígonos
    de tierra (land_polygons) para dibujar la costa."""
    import matplotlib.pyplot as plt
    from ..gui.figures import NodeSampler, _values, map_arrows, dataset_range, LABELS
    from .sections import field_at_depth
    smp = NodeSampler(ds, n=n)
    is3d = (var + "X" if var + "X" in ds else var) in ds and "layer" in ds[var + "X" if var + "X" in ds else var].dims
    def field(it):
        if is3d and depth_m is not None:
            if var + "X" in ds:
                return np.hypot(field_at_depth(ds, var + "X", it, depth_m, vg), field_at_depth(ds, var + "Y", it, depth_m, vg))
            return field_at_depth(ds, var, it, depth_m, vg)
        return _values(ds, var, it, layer)
    zr = dataset_range(ds, var, layer)
    its = list(range(0, ds.time.size, max(1, step)))
    fig, ax = plt.subplots(figsize=(12.8, 7.2))
    writer = _writer(fps)
    asp = 1 / np.cos(np.deg2rad(float(ds.y.values.mean()))) if np.ptp(ds.y.values) < 180 else 1.0
    with writer.saving(fig, str(out), dpi=100):
        for k, it in enumerate(its):
            ax.clear()
            Z = smp.grid(field(it))
            pm = ax.pcolormesh(smp.xi, smp.yi, Z, cmap="RdBu_r" if var == "elevation" else ("RdYlBu_r" if var == "temperature" else "viridis"), vmin=zr[0], vmax=zr[1], shading="auto")
            if arrows:
                tr, vmax = map_arrows(ds, it, layer, depth_m=depth_m, vg=vg)
                ax.plot(tr.x, tr.y, "k-", lw=0.7)
                ax.text(0.99, 0.02, f"|u| máx {vmax:.2f} m/s" if lang == "es" else f"|u| max {vmax:.2f} m/s", transform=ax.transAxes, ha="right", fontsize=9, bbox=dict(fc="w", alpha=0.7, ec="none"))
            for lx, ly in (land or []):
                ax.fill(np.nan_to_num(lx, nan=np.nan), ly, color="#dedcd7", ec="#6d6d6d", lw=0.6)
            ax.set_xlim(smp.xi.min(), smp.xi.max()); ax.set_ylim(smp.yi.min(), smp.yi.max())
            ax.set_aspect(asp); ax.set_title(f"{LABELS.get(var, var)} · {np.datetime_as_string(ds.time.values[it], 'm').replace('T', ' ')}")
            if k == 0:
                fig.colorbar(pm, ax=ax, label=LABELS.get(var, var))
            writer.grab_frame()
            if progress:
                progress((k + 1) / len(its))
    plt.close(fig)
    return out


def section_video(ds, sec, var: str, out, arrows: bool = True, wfactor: float = 200.0, fps: int = 8, step: int = 1, progress=None, lang: str = "es"):
    """MP4 de una sección vertical (objeto Section) con isolíneas y flechas (u‖, w·wfactor)."""
    import matplotlib.pyplot as plt
    from ..gui.figures import LABELS, section_figure2
    its = list(range(0, ds.time.size, max(1, step)))
    vals = [sec.scalar(var, it) for it in its[:: max(1, len(its) // 6)]]
    zr = (float(np.nanmin([np.nanmin(v) for v in vals])), float(np.nanmax([np.nanmax(v) for v in vals])))
    fig, ax = plt.subplots(figsize=(12.8, 6.4))
    writer = _writer(fps)
    with writer.saving(fig, str(out), dpi=100):
        for k, it in enumerate(its):
            ax.clear()
            f = section_figure2(sec, var, it, arrows=arrows, contours=True, wfactor=wfactor, zrange=zr, lang=lang)
            hm = f.data[0]
            pm = ax.pcolormesh(np.asarray(hm.x), np.asarray(hm.y), np.array(hm.z, float), cmap="RdYlBu_r" if var == "temperature" else "viridis", vmin=zr[0], vmax=zr[1], shading="auto")
            for tr in f.data[1:]:
                if tr.type == "scatter" and tr.mode == "lines" and tr.fill:
                    ax.fill_between(np.asarray(tr.x), np.asarray(tr.y, float), np.nanmin(np.asarray(hm.y)), color="#777")
                elif tr.type == "scatter" and tr.line is not None and tr.line.width == 0:
                    continue                                                      # línea base invisible del relleno
                elif tr.type == "scatter":
                    ax.plot(np.asarray(tr.x, float), np.asarray(tr.y, float), "k-", lw=0.7)
                elif tr.type == "contour":
                    ax.contour(np.asarray(tr.x), np.asarray(tr.y), np.array(tr.z, float), levels=10, colors="k", linewidths=0.5, alpha=0.5)
            ax.set_xlabel("distancia (km)" if lang == "es" else "distance (km)"); ax.set_ylabel("z (m)")
            ax.set_title(f"{LABELS.get(var, var)} · {np.datetime_as_string(ds.time.values[it], 'm').replace('T', ' ')}")
            if k == 0:
                fig.colorbar(pm, ax=ax, label=LABELS.get(var, var))
            writer.grab_frame()
            if progress:
                progress((k + 1) / len(its))
    plt.close(fig)
    return out
