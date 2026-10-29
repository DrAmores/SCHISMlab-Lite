"""Forzamiento atmosferico: ficheros sflux (nws=2) y viento uniforme wind.th (nws=1)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import xarray as xr

DEFAULTS = dict(prmsl=101325.0, stmp=293.0, spfh=0.0104)


def write_wind_th(path: str | Path, times_s: np.ndarray, u: np.ndarray, v: np.ndarray) -> None:
    """wind.th para nws=1: viento uniforme en el espacio, serie temporal (t en s desde el inicio)."""
    np.savetxt(path, np.column_stack([times_s, u, v]), fmt="%.3f")


def write_sflux(outdir: str | Path, lon: np.ndarray, lat: np.ndarray, times: np.ndarray, fields: dict,
                start: np.datetime64, days_per_file: int = 31, extra: dict | None = None) -> list[Path]:
    """Escribe sflux/sflux_air_1.NNNN.nc (+ sflux_inputs.txt) a partir de campos (time, lat, lon).

    lon, lat : vectores 1D de la rejilla atmosferica (grados)
    times    : np.datetime64[...] (ascendentes, cubriendo [start, start+rnday] con margen)
    fields   : {'uwind': (nt, ny, nx), 'vwind': ..., opcional 'prmsl', 'stmp', 'spfh'}
    """
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("sflux_*.nc"):                      # sin restos de un setup anterior (otra duración u otra rejilla)
        old.unlink()
    (outdir / "sflux_inputs.txt").write_text("&sflux_inputs\n/\n")
    LON, LAT = np.meshgrid(lon, lat)
    # SCHISM toma de base_date solo el día (la hora no cuenta): los tiempos van desde las 00:00 del día de inicio, si no
    # una simulación que empieza a las 17:15 busca el forzamiento a las 00:00 y se para («no appropriate time exists»)
    start = np.datetime64(start, "D").astype("datetime64[s]")
    tdays = (np.asarray(times, "datetime64[s]") - start) / np.timedelta64(1, "D")
    nt = len(tdays)
    files = []
    chunk = max(1, int(round(days_per_file / max(float(np.median(np.diff(tdays))), 1e-6))))
    for n, i0 in enumerate(range(0, nt, chunk), start=1):
        sl = slice(i0, min(i0 + chunk, nt))
        data = {}
        for k in ("uwind", "vwind", "prmsl", "stmp", "spfh"):
            arr = fields.get(k)
            if arr is None:
                arr = np.full((nt,) + LON.shape, DEFAULTS[k])
            data[k] = (("time", "ny_grid", "nx_grid"), np.asarray(arr, "float32")[sl])
        ds = xr.Dataset(data, coords={"time": ("time", tdays[sl].astype("float32")),
                                      "lon": (("ny_grid", "nx_grid"), LON.astype("float32")),
                                      "lat": (("ny_grid", "nx_grid"), LAT.astype("float32"))})
        y, mo, d = [int(s) for s in np.datetime_as_string(start, "D").split("-")]
        ds.time.attrs.update(long_name="Time", standard_name="time", units=f"days since {y:04d}-{mo:02d}-{d:02d} 00:00:00",
                             base_date=np.array([y, mo, d, 0], "int32"))
        ds.lon.attrs.update(long_name="Longitude", standard_name="longitude", units="degrees_east")
        ds.lat.attrs.update(long_name="Latitude", standard_name="latitude", units="degrees_north")
        ds.uwind.attrs.update(long_name="Surface Eastward Air Velocity (10m AGL)", standard_name="eastward_wind", units="m/s")
        ds.vwind.attrs.update(long_name="Surface Northward Air Velocity (10m AGL)", standard_name="northward_wind", units="m/s")
        ds.prmsl.attrs.update(long_name="Pressure reduced to MSL", standard_name="air_pressure_at_sea_level", units="Pa")
        ds.stmp.attrs.update(long_name="Surface Air Temperature (2m AGL)", standard_name="air_temperature", units="K")
        ds.spfh.attrs.update(long_name="Surface Specific Humidity (2m AGL)", standard_name="specific_humidity", units="1")
        ds.attrs["Conventions"] = "CF-1.0"
        f = outdir / f"sflux_air_1.{n:04d}.nc"
        ds.to_netcdf(f, format="NETCDF4", encoding={"time": {"dtype": "float32"}})
        files.append(f)
        # radiacion (sflux_rad) y precipitacion (sflux_prc) si se han dado
        for kind, names in (("rad", ("dswrf", "dlwrf")), ("prc", ("prate",))):
            if extra and all(k in extra for k in names):
                d2 = ds[["time", "lon", "lat"]].copy() if False else xr.Dataset(coords=ds.coords)
                for k in names:
                    d2[k] = (("time", "ny_grid", "nx_grid"), np.asarray(extra[k], "float32")[sl])
                d2.time.attrs.update(ds.time.attrs); d2.lon.attrs.update(ds.lon.attrs); d2.lat.attrs.update(ds.lat.attrs)
                d2.attrs["Conventions"] = "CF-1.0"
                d2.to_netcdf(outdir / f"sflux_{kind}_1.{n:04d}.nc", format="NETCDF4", encoding={"time": {"dtype": "float32"}})
    return files
