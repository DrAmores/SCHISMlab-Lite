"""Análisis de series temporales: series en puntos, espectro de Welch, espectro rotatorio y wavelet de Morlet
(Torrence & Compo, 1998) con cono de influencia y significación frente a ruido rojo."""
from __future__ import annotations
import numpy as np
import xarray as xr
from scipy import signal as sig
from scipy.stats import chi2

OMEGA_SIDEREAL = 7.292115e-5


def reference_periods(lat: float | None = None) -> dict:
    """Periodos de referencia en horas: constituyentes de marea y periodo inercial de la latitud."""
    p = {"M2": 12.4206, "S2": 12.0, "N2": 12.6583, "K1": 23.9345, "O1": 25.8193}
    if lat is not None and abs(lat) > 1e-3:
        f = 2 * OMEGA_SIDEREAL * np.sin(np.deg2rad(lat))
        p["inercial"] = 2 * np.pi / abs(f) / 3600
    return p


def regularize(t, y):
    """Serie en una malla temporal uniforme (interpolando huecos y pasos irregulares). Devuelve (t_seg, y, dt_seg)."""
    t = np.asarray(t)
    ts = (t - t[0]) / np.timedelta64(1, "s") if np.issubdtype(t.dtype, np.datetime64) else np.asarray(t, float) - float(t[0])
    y = np.asarray(y, float)
    ok = np.isfinite(y)
    dt = float(np.median(np.diff(ts)))
    tu = np.arange(0.0, ts[-1] + 0.5 * dt, dt)
    yu = np.interp(tu, ts[ok], y[ok]) if ok.sum() >= 2 else np.full(tu.size, np.nan)
    return tu, yu, dt


def detrend(y: np.ndarray) -> np.ndarray:
    return sig.detrend(np.asarray(y, float), type="linear")


def psd_welch(y, dt: float, nperseg: int | None = None, overlap: float = 0.5, window: str = "hann", conf: float = 0.95):
    """Densidad espectral de potencia (Welch). Devuelve dict(f [Hz], period_h, P, lo, hi, dof): intervalo de
    confianza chi-cuadrado con dof ≈ 2 × número de segmentos (aproximación para ventana Hann y 50 % de solape)."""
    y = detrend(y); n = y.size
    nperseg = int(nperseg or max(16, min(n, n // 4 * 2 if n >= 64 else n)))
    nperseg = min(nperseg, n)
    noverlap = int(overlap * nperseg)
    f, P = sig.welch(y, fs=1.0 / dt, window=window, nperseg=nperseg, noverlap=noverlap, detrend="linear")
    nseg = max(1, 1 + (n - nperseg) // max(1, nperseg - noverlap))
    dof = 2 * nseg
    lo, hi = dof / chi2.ppf((1 + conf) / 2, dof), dof / chi2.ppf((1 - conf) / 2, dof)
    f, P = f[1:], P[1:]
    return dict(f=f, period_h=1.0 / f / 3600, P=P, lo=P * lo, hi=P * hi, dof=dof, nperseg=nperseg)


def rotary_spectrum(u, v, dt: float, nperseg: int | None = None, overlap: float = 0.5):
    """Espectro rotatorio de u + i v: potencia horaria (CW, frecuencias negativas) y antihoraria (CCW).
    En el hemisferio norte las oscilaciones inerciales giran en sentido horario."""
    w = detrend(np.asarray(u, float)) + 1j * detrend(np.asarray(v, float)); n = w.size
    nperseg = min(int(nperseg or max(16, n // 2)), n)
    f, P = sig.welch(w, fs=1.0 / dt, nperseg=nperseg, noverlap=int(overlap * nperseg), return_onesided=False, detrend=False)
    f, P = np.fft.fftshift(f), np.fft.fftshift(P.real)
    pos = f > 0; neg = f < 0
    fp = f[pos]
    return dict(f=fp, period_h=1.0 / fp / 3600, ccw=P[pos], cw=P[neg][::-1][:fp.size])   # con nperseg par, f < 0 incluye Nyquist: un punto más


def _ar1(y: np.ndarray) -> float:
    """Autocorrelación lag-1 del ruido rojo equivalente (Torrence & Compo: (r1 + sqrt(r2)) / 2)."""
    y = y - y.mean()
    def r(k):
        return float(np.sum(y[:-k] * y[k:]) / np.sum(y * y)) if y.size > k else 0.0
    r1, r2 = r(1), r(2)
    return float(np.clip((r1 + np.sqrt(max(r2, 0.0))) / 2, 0.0, 0.99))


def wavelet_morlet(y, dt: float, dj: float = 0.125, s0: float | None = None, J: int | None = None, omega0: float = 6.0,
                   conf: float = 0.95) -> dict:
    """Transformada wavelet continua de Morlet (Torrence & Compo 1998).

    Devuelve dict con: t (s desde el inicio), period (s), scale, power (nscale, n), coi (s; periodo del cono de
    influencia en cada instante), glob (espectro global), signif (nscale: nivel al `conf` frente a ruido rojo AR1),
    glob_signif, alpha (AR1) y var. power/signif[:, None] > 1 marca las zonas significativas.
    """
    y = detrend(np.asarray(y, float)); n = y.size
    var = float(y.var()) or 1.0
    s0 = s0 or 2 * dt
    J = J if J is not None else int(np.log2(n * dt / s0) / dj)
    scale = s0 * 2.0 ** (dj * np.arange(J + 1))
    npad = int(2 ** np.ceil(np.log2(n)))
    k = 2 * np.pi * np.fft.fftfreq(npad, dt)
    yh = np.fft.fft(np.concatenate([y, np.zeros(npad - n)]))
    W = np.empty((scale.size, n), complex)
    for j, s in enumerate(scale):
        psi = np.pi ** -0.25 * np.exp(-0.5 * (s * k - omega0) ** 2) * (k > 0) * np.sqrt(2 * np.pi * s / dt)
        W[j] = np.fft.ifft(yh * np.conj(psi))[:n]
    fourier = 4 * np.pi / (omega0 + np.sqrt(2 + omega0 ** 2))
    period = fourier * scale
    power = np.abs(W) ** 2
    t = np.arange(n) * dt
    coi = fourier / np.sqrt(2) * dt * np.minimum(np.arange(n), np.arange(n)[::-1])     # e-folding: periodo del cono
    # significación frente a ruido rojo (chi2 con 2 grados de libertad, espectro teórico AR1 en la frecuencia de cada escala)
    alpha = _ar1(y)
    freq = dt / period
    Pk = (1 - alpha ** 2) / (1 + alpha ** 2 - 2 * alpha * np.cos(2 * np.pi * freq))
    signif = var * Pk * chi2.ppf(conf, 2) / 2
    glob = power.mean(1)
    # espectro global: dof efectivos (eq. 23, Morlet: gamma = 2.32, dofmin = 2)
    dof = 2 * np.sqrt(1 + (n * dt / (2.32 * scale)) ** 2)
    glob_signif = var * Pk * chi2.ppf(conf, dof) / dof
    return dict(t=t, period=period, scale=scale, power=power, coi=coi, glob=glob, signif=signif, glob_signif=glob_signif,
                alpha=alpha, var=var, omega0=omega0)


def resolvable_periods(dt: float, n: int) -> tuple[float, float]:
    """(periodo mínimo, periodo máximo) en segundos que tiene sentido analizar: 2 dt y un cuarto del registro."""
    return 2 * dt, n * dt / 4


def point_series(ds: xr.Dataset, var: str, node: int, layer: int | None = None):
    """Serie temporal en un nodo (componentes u, v si la variable es vector). Devuelve dict(t, y | u, v)."""
    t = ds.time.values
    if var + "X" in ds:
        u, v = ds[var + "X"].isel(node=node), ds[var + "Y"].isel(node=node)
        if "layer" in u.dims:
            u, v = u.isel(layer=layer if layer is not None else -1), v.isel(layer=layer if layer is not None else -1)
        return dict(t=t, u=u.values.astype(float), v=v.values.astype(float))
    da = ds[var].isel(node=node)
    if "layer" in da.dims:
        da = da.isel(layer=layer if layer is not None else -1)
    return dict(t=t, y=da.values.astype(float))
