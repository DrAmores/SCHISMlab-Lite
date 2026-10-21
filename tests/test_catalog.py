"""Catálogo de parámetros .nml, variantes de compilación y sobreescrituras."""
from pathlib import Path
from schismlab.io.namelist_catalog import catalog, sections, is_auto, template_path, NAMELISTS
from schismlab.io.param import write_param
from schismlab.build import variant_name, normalize, required_namelists


def test_catalog_param():
    c = catalog("param.nml"); names = {e.name for e in c}
    assert {"rnday", "dt", "nchi", "iof_hydro(1)", "nspool"} <= names
    assert sections("param.nml") == ["CORE", "OPT", "SCHOUT"]
    rn = next(e for e in c if e.name == "rnday")
    assert rn.help("es") and rn.help("en") and is_auto(rn)
    assert all(catalog(n) for n in NAMELISTS)


def test_wwm_entries_tagged():
    assert all(e.modules == ["wwm"] for e in catalog("wwminput.nml"))
    c = catalog("param.nml")
    assert next(e for e in c if e.name == "iof_wwm(1)").modules == ["wwm"]
    assert next(e for e in c if e.name == "nchi").modules == []


def test_variant_names():
    assert variant_name(["prec_evap"]) == "hydro"
    assert variant_name(["USE_WWM", "PREC_EVAP"]) == "wwm"
    assert variant_name(["wwm", "sed", "prec_evap"]) == "wwm+sed"
    assert variant_name(["sed"]) == "hydro+sed-noprec"
    assert normalize(["sed", "wwm"]) == ["wwm", "sed"]
    assert required_namelists(["wwm", "sed"]) == ["wwminput.nml", "sediment.nml"]


def test_write_other_namelist(tmp_path: Path):
    out = tmp_path / "sediment.nml"
    write_param(out, {"Nbed": 3}, template=template_path("sediment.nml"))
    assert "Nbed = 3" in out.read_text()
