"""Lectura de las salidas de SCHISM (scribed I/O: out2d_N.nc + <variable>_N.nc) como un Dataset de xarray."""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import xarray as xr

NODE, LAYER = "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers"


def open_run(rundir: str | Path, variables: list[str] | None = None) -> xr.Dataset:
    """Abre todas las pilas (stacks) de outputs/ y las concatena en el tiempo.

    Devuelve un Dataset con las variables 2D de out2d y las 3D pedidas (por defecto todas las
    disponibles), mas la malla (x, y, depth, elements 0-based) como variables.
    """
    out = Path(rundir) / "outputs" if (Path(rundir) / "outputs").is_dir() else Path(rundir)
    stacks = sorted(int(m.group(1)) for f in out.glob("out2d_*.nc") if (m := re.match(r"out2d_(\d+)\.nc", f.name)))
    def readable(n):
        try:
            with xr.open_dataset(out / f"out2d_{n}.nc") as d:
                return d.sizes.get("time", 0) > 0
        except Exception:   # noqa: BLE001  (pila truncada o corrupta)
            return False
    stacks = [n for n in stacks if readable(n)]
    if not stacks:
        raise FileNotFoundError(f"no hay out2d_*.nc legibles en {out}")
    # pilas de otra simulación (malla distinta) que quedaron en la carpeta: se ignoran con aviso
    def nnodes(n):
        with xr.open_dataset(out / f"out2d_{n}.nc") as d:
            return d.sizes.get(NODE, 0)
    n0 = nnodes(stacks[0]); bad = [n for n in stacks if nnodes(n) != n0]
    if bad:
        import logging
        logging.getLogger(__name__).warning("pilas ignoradas por tener otra malla (%s nodos frente a %s): %s", [nnodes(n) for n in bad], n0, bad)
        stacks = [n for n in stacks if n not in bad]
    ds2 = xr.open_mfdataset([out / f"out2d_{n}.nc" for n in stacks], combine="nested", concat_dim="time",
                            data_vars="minimal", coords="minimal", compat="override")
    avail = sorted({re.match(r"(.+)_\d+\.nc", f.name).group(1) for f in out.glob("*_1.nc")} - {"out2d"})
    variables = avail if variables is None else [v for v in variables if v in avail]
    parts = [ds2]
    for v in variables:
        parts.append(xr.open_mfdataset([out / f"{v}_{n}.nc" for n in stacks], combine="nested", concat_dim="time"))
    ds = xr.merge(parts, compat="override")
    first = xr.open_dataset(out / f"out2d_{stacks[0]}.nc")
    ds = ds.assign(x=first["SCHISM_hgrid_node_x"].values, y=first["SCHISM_hgrid_node_y"].values)
    ds = ds.rename({NODE: "node"} if NODE in ds.dims else {})
    if LAYER in ds.dims:
        ds = ds.rename({LAYER: "layer"})
    ds.attrs["elements"] = (first["SCHISM_hgrid_face_nodes"].values[:, :3].astype(int) - 1)
    ds.attrs["rundir"] = str(rundir)
    return ds


def nearest_node(ds: xr.Dataset, x: float, y: float) -> int:
    return int(np.argmin((ds.x.values - x) ** 2 + (ds.y.values - y) ** 2))


def profile(ds: xr.Dataset, var: str, x: float, y: float, time=-1) -> xr.DataArray:
    """Perfil vertical de `var` en el nodo mas cercano a (x, y) y el instante `time` (indice o fecha)."""
    n = nearest_node(ds, x, y)
    da = ds[var].isel(node=n)
    return da.isel(time=time) if isinstance(time, int) else da.sel(time=time, method="nearest")


def layer_depths(ds: xr.Dataset, vg, node: int, eta: float = 0.0) -> np.ndarray:
    """Cotas z de los niveles de un nodo (usa la malla vertical VGrid del caso)."""
    return vg.zcor(np.array([float(ds.depth.isel(node=node))]), np.array([eta]))[0]


def read_stations(rundir: str | Path, variable: str = "elev", start=None):
    """Series de las estaciones (station.in) como DataFrame con una columna por estacion."""
    import pandas as pd, yaml
    rundir = Path(rundir)
    idx = {"elev": 1, "airP": 2, "windx": 3, "windy": 4, "T": 5, "S": 6, "u": 7, "v": 8, "w": 9}[variable]
    f = rundir / "outputs" / f"staout_{idx}"
    if not f.exists() and (rundir / f"staout_{idx}").exists():       # simulación archivada: outputs_<fecha>/ es la propia carpeta de salidas
        f = rundir / f"staout_{idx}"
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = np.loadtxt(f)
    if data.size == 0 or data.ndim < 2:
        raise ValueError(f"la simulación no guardó la variable '{variable}' en las estaciones ({f.name} vacío)")
    names = []
    for line in (rundir / "station.in").read_text().splitlines()[2:]:
        names.append(line.split("!")[-1].strip() if "!" in line else str(len(names) + 1))
    if start is None:
        import re
        p = (rundir / "param.nml").read_text()
        g = lambda k: int(float(re.search(rf"^\s*{k}\s*=\s*([\d.]+)", p, re.M).group(1)))
        start = np.datetime64(f"{g('start_year'):04d}-{g('start_month'):02d}-{g('start_day'):02d}", "s") + np.timedelta64(g("start_hour") * 3600, "s")
    t = np.datetime64(start, "s") + (data[:, 0] * 1e9).astype("timedelta64[ns]")
    return pd.DataFrame(data[:, 1:], index=pd.DatetimeIndex(t), columns=names)


def crop_outputs(rundir: str | Path, lon: tuple[float, float], lat: tuple[float, float], out_name: str = "outputs_recorte") -> Path:
    """Recorta todas las salidas (out2d_N.nc y <var>_N.nc) a un rectángulo [lon0, lon1] x [lat0, lat1] (o x/y) y las
    escribe en <rundir>/<out_name>/ con el mismo formato (nodos, elementos y lados renumerados): SCHISM solo escribe
    el dominio completo, así que el subdominio se obtiene después de la simulación."""
    rundir = Path(rundir); src = rundir / "outputs"; dst = rundir / out_name; dst.mkdir(exist_ok=True)
    stacks = sorted(int(m.group(1)) for f in src.glob("out2d_*.nc") if (m := re.match(r"out2d_(\d+)\.nc", f.name)))
    if not stacks:
        raise FileNotFoundError(f"no hay out2d_*.nc en {src}")
    with xr.open_dataset(src / f"out2d_{stacks[0]}.nc") as d0:
        x, y = d0["SCHISM_hgrid_node_x"].values, d0["SCHISM_hgrid_node_y"].values
        faces = d0["SCHISM_hgrid_face_nodes"].values            # (ne, 4) 1-based, -1 o fill en triángulos
        edges = d0["SCHISM_hgrid_edge_nodes"].values if "SCHISM_hgrid_edge_nodes" in d0 else None
    keep = (x >= min(lon)) & (x <= max(lon)) & (y >= min(lat)) & (y <= max(lat))
    if keep.sum() < 3:
        raise ValueError("el rectángulo no contiene nodos de la malla")
    new = -np.ones(x.size, int); new[keep] = np.arange(keep.sum())
    f = np.nan_to_num(np.asarray(faces, float), nan=0).astype(int) - 1       # -1 = sin nodo (triángulos en tabla de 4)
    fkeep = np.all((f < 0) | keep[np.maximum(f, 0)], axis=1) & (f[:, 0] >= 0)
    fnew = np.where(f[fkeep] >= 0, new[np.maximum(f[fkeep], 0)] + 1, np.nan).astype(float)
    if edges is not None:
        e = np.nan_to_num(np.asarray(edges, float), nan=0).astype(int) - 1
        ekeep = (e.min(1) >= 0) & keep[np.maximum(e[:, 0], 0)] & keep[np.maximum(e[:, 1], 0)]; enew = (new[e[ekeep]] + 1).astype(float)
    for n in stacks:
        for fsrc in sorted(src.glob(f"*_{n}.nc")):
            if not re.match(r"(.+)_\d+\.nc", fsrc.name):
                continue
            with xr.open_dataset(fsrc) as d:
                sel = {}
                if NODE in d.dims: sel[NODE] = np.where(keep)[0]
                if "nSCHISM_hgrid_face" in d.dims: sel["nSCHISM_hgrid_face"] = np.where(fkeep)[0]
                if "nSCHISM_hgrid_edge" in d.dims and edges is not None: sel["nSCHISM_hgrid_edge"] = np.where(ekeep)[0]
                dc = d.isel(**sel).load()
                if "SCHISM_hgrid_face_nodes" in dc:
                    dc["SCHISM_hgrid_face_nodes"] = (dc["SCHISM_hgrid_face_nodes"].dims, fnew, dc["SCHISM_hgrid_face_nodes"].attrs)
                if "SCHISM_hgrid_edge_nodes" in dc and edges is not None:
                    dc["SCHISM_hgrid_edge_nodes"] = (dc["SCHISM_hgrid_edge_nodes"].dims, enew, dc["SCHISM_hgrid_edge_nodes"].attrs)
                dc.attrs["cropped_from"] = str(src); dc.attrs["crop_lon"] = list(map(float, lon)); dc.attrs["crop_lat"] = list(map(float, lat))
                dc.to_netcdf(dst / fsrc.name)
    for extra in ("station.in", "param.nml"):
        if (rundir / extra).exists() and not (dst / extra).exists():
            (dst / extra).write_bytes((rundir / extra).read_bytes())
    return dst


def run_vgrid(wd, ds=None, cfg: dict | None = None):
    """Malla vertical de la simulación de la carpeta `wd`: su caso.yaml y su vgrid.in (los archivados llevan copia) y, si no
    cuadran o no existen (p. ej. vgrid LSC2 de una malla importada), una sigma con el número de niveles del dataset."""
    import yaml
    from ..forcing import VGrid
    wd = Path(wd)
    nl = int(ds.sizes.get("layer", 1)) if ds is not None else None
    c = cfg or {}
    c_run = c
    if (wd / "caso.yaml").exists():
        try:
            c_run = yaml.safe_load((wd / "caso.yaml").read_text(encoding="utf-8")) or c
        except Exception:   # noqa: BLE001
            c_run = c
    v = c_run.get("vertical") or {"type": "2d"}
    vg = None
    try:
        if v.get("type") == "sigma":
            vg = VGrid.sigma(int(v.get("nvrt", 20)), float(v.get("h_c", 10)), float(v.get("theta_b", 0)), float(v.get("theta_f", 4)))
        elif v.get("type") == "sz":
            vf = wd / "vgrid.in"
            if vf.exists():
                txt = vf.read_text().splitlines()
                if int(txt[0].split()[0]) != 2:                          # ivcor = 1 (LSC2): no se parsea
                    raise ValueError("vgrid LSC2")
                nvrt, kz, hs = txt[1].split()[:3]; z = [float(txt[3 + k].split()[1]) for k in range(int(kz) - 1)] + [-float(hs)]
                hc, tb, tf = [float(x) for x in txt[4 + int(kz)].split()[:3]]
                vg = VGrid.sz(int(nvrt) - int(kz) + 1, z, hc, tb, tf)
            else:
                vg = VGrid.sz(int(v.get("nsigma", 20)), [float(z_) for z_ in v.get("zlevels", [-1000])], float(v.get("h_c", 10)), float(v.get("theta_b", 0.5)), float(v.get("theta_f", 4)))
        else:
            vg = VGrid.two_d()
    except Exception:   # noqa: BLE001  (vgrid ilegible: se deduce del dataset)
        vg = None
    if vg is not None and (nl is None or vg.nvrt == nl):
        return vg
    if nl is not None and nl > 2:
        return VGrid.sigma(nl, float(v.get("h_c", 10) or 10), 0.0, float(v.get("theta_f", 4) or 4))
    if nl is not None and nl <= 2:                                  # el dataset es 2D aunque el caso diga otra cosa
        return VGrid.two_d()
    return VGrid.two_d() if vg is None else vg


def auto_vgrid(ds: xr.Dataset):
    """Malla vertical de la simulación de la que viene `ds` (abierto con open_run), para los cálculos en 3D sin la salida
    zCoordinates; None si no se puede saber."""
    if "_vgrid" not in ds.attrs:
        try:
            ds.attrs["_vgrid"] = run_vgrid(ds.attrs["rundir"], ds) if ds.attrs.get("rundir") else None
        except Exception:   # noqa: BLE001
            ds.attrs["_vgrid"] = None
    return ds.attrs["_vgrid"]
