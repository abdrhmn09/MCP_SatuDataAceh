"""Bounded samples and dependencies for the dashboard BPS diagnostic."""

from . import bps_api

# Fallback samples for detail operations come from the BPS OpenAPI examples.
SAMPLES = {
    "listDomains": {"type": "prov"},
    "listSubjects": {"domain": "1100", "page": 1},
    "listSubjectCategories": {"domain": "1100", "page": 1},
    "listVariables": {"domain": "1100", "page": 1},
    "listVerticalVariables": {"domain": "1100", "page": 1},
    "listDerivedVariables": {"domain": "1100", "page": 1},
    "listPeriods": {"domain": "1100", "page": 1},
    "listDerivedPeriods": {"domain": "1100", "page": 1},
    "listUnits": {"domain": "1100", "page": 1},
    "getData": {"domain": "0000", "var": 145, "th": "100"},
    "listStaticTables": {"domain": "1100", "page": 1},
    "getStaticTable": {"domain": "0000", "lang": "ind", "id": 111},
    "listCsaSubjectCategories": {"domain": "1100"},
    "listCsaSubjects": {"domain": "1100"},
    "listCsaTables": {"domain": "1100", "page": 1, "perpage": 10},
    "getCsaTable": {"domain": "0000", "id": "1", "lang": "ind"},
    "listPressReleases": {"domain": "1100", "page": 1},
    "getPressRelease": {"domain": "0000", "lang": "ind", "id": "brs-13342312"},
    "listPublications": {"domain": "1100", "page": 1},
    "getPublication": {"domain": "0000", "lang": "ind", "id": "pub-13342312"},
    "listStrategicIndicators": {"domain": "1100", "page": 1},
    "listInfographics": {"domain": "1100", "page": 1},
    "listNews": {"domain": "1100", "page": 1},
    "getNews": {"domain": "0000", "lang": "ind", "id": 9},
    "listNewsCategories": {"domain": "1100"},
    "listGlossary": {"page": 1, "perpage": 10, "prefix": "a"},
    "getGlossaryEntry": {"id": 4406, "lang": "ind"},
    "getForeignTrade": {"sumber": 1, "periode": 2, "kodehs": "03;04", "jenishs": 1, "tahun": "2019"},
    "listSdgsTables": {},
    "listSddsTables": {},
    "listClassifications": {"model": "kbli2020", "page": 1, "perpage": 10},
    "getClassification": {"model": "kbli2020", "id": "kbli_2020_011", "lang": "ind"},
    "listCensusEvents": {},
    "listCensusTopics": {"kegiatan": "sp2020"},
    "listCensusAreas": {"kegiatan": "sp2020"},
    "listCensusDatasets": {"kegiatan": "sp2020", "topik": 1},
    "getCensusData": {"kegiatan": "sp2020", "wilayah_sensus": 1, "dataset": 1},
    "listSimdasiProvinces": {},
    "listSimdasiRegencies": {"parent": "1100000"},
    "listSimdasiDistricts": {"parent": "3171000"},
    "listSimdasiSubjects": {"wilayah": "1100000"},
    "listSimdasiMasterTables": {},
    "getSimdasiMasterTable": {"id_tabel": "UFpWMmJZOVZlZTJnc1pXaHhDV1hPQT09"},
    "listSimdasiTables": {"wilayah": "1100000"},
    "listSimdasiTablesBySubject": {"wilayah": "3100000", "id_subjek": "516"},
    "getSimdasiTable": {"wilayah": "3100000", "tahun": 2021, "id_tabel": "UFpWMmJZOVZlZTJnc1pXaHhDV1hPQT09"},
    "searchContent": {"model": "publication", "domain": "1100", "page": 1, "perpage": 10},
    "getSdgsHome": {},
    "listSdgsGoals": {},
    "getSdgsGoal": {"id": "2"},
    "listSdgsIndicators": {},
    "getSdgsIndicator": {"id": "2"},
    "listSdgsDatasets": {"page[number]": 1, "page[size]": 10},
    "getSdgsDataset": {"id": "2"},
    "getSdgsDatasetRelationship": {"id": "2", "relationships": "data"},
    "listForeignTradeYears": {},
    "listForeignTradePorts": {"page": 1, "limit": 10},
    "listForeignTradeCountries": {"page": 1, "limit": 10},
    "listForeignTradeHsCodes": {"page": 1, "limit": 10, "type": 1},
}

# Sources must run before operations that reuse their identifiers.
DETAILS = {
    "getStaticTable": ("listStaticTables", ("table_id", "id")),
    "getCsaTable": ("listCsaTables", ("id", "table_id", "id_tabel")),
    "getPressRelease": ("listPressReleases", ("brs_id", "id")),
    "getPublication": ("listPublications", ("pub_id", "id")),
    "getNews": ("listNews", ("news_id", "id")),
    "getGlossaryEntry": ("listGlossary", ("id",)),
    "getClassification": ("listClassifications", ("id",)),
    "getSdgsGoal": ("listSdgsGoals", ("id",)),
    "getSdgsIndicator": ("listSdgsIndicators", ("id",)),
    "getSdgsDataset": ("listSdgsDatasets", ("id",)),
    "getSdgsDatasetRelationship": ("listSdgsDatasets", ("id",)),
    "getSimdasiMasterTable": ("listSimdasiMasterTables", ("id_tabel", "id")),
}
DEPENDENCIES = {operation: (source,) for operation, (source, _) in DETAILS.items()}
DEPENDENCIES.update({
    "listVerticalVariables": ("listVariables",),
    "listDerivedVariables": ("listVariables",),
    "listPeriods": ("listVariables",),
    "listDerivedPeriods": ("listVariables",),
    "getData": ("listPeriods",),
    "getForeignTrade": ("listForeignTradeYears",),
    "listCensusTopics": ("listCensusEvents",),
    "listCensusAreas": ("listCensusEvents",),
    "listCensusDatasets": ("listCensusTopics",),
    "getCensusData": ("listCensusDatasets", "listCensusAreas"),
    "listSimdasiDistricts": ("listSimdasiRegencies",),
    "listSimdasiTablesBySubject": ("listSimdasiSubjects",),
    "getSimdasiTable": ("listSimdasiTables",),
})


def ordered_operations():
    emitted = set()
    for name in bps_api.OPERATIONS:
        for operation in (*DEPENDENCIES.get(name, ()), name):
            if operation not in emitted:
                emitted.add(operation)
                yield operation


def _field(row, names):
    for record in (row, row.get("_source"), row.get("attributes")):
        if isinstance(record, dict):
            for name in names:
                value = record.get(name)
                if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
                    return value
    return None


def sample_parameters(operation, previous):
    sample = SAMPLES[operation].copy()

    def rows(source):
        result, _ = previous.get(source, ({}, {}))
        return bps_api.rows(result.get("data")) if result.get("ok") else []

    def params(source):
        return previous.get(source, ({}, {}))[1]

    def find(source, *names):
        return next((value for row in rows(source) if (value := _field(row, names)) is not None), None)

    if operation in DETAILS:
        source, keys = DETAILS[operation]
        for row in rows(source):
            value = _field(row, keys)
            if value is None:
                continue
            field = "id_tabel" if operation == "getSimdasiMasterTable" else "id"
            sample[field] = value
            if "domain" in sample:
                sample["domain"] = params(source)["domain"]
            if operation == "getCsaTable":
                year = _field(row, ("latest_period", "year"))
                if year and len(str(year)) == 4 and str(year).isdigit():
                    sample["year"] = int(year)
            break
    elif operation in {"listVerticalVariables", "listDerivedVariables", "listPeriods", "listDerivedPeriods"}:
        sample["var"] = find("listVariables", "var_id") or 564
    elif operation == "getData":
        period = find("listPeriods", "th_id")
        if period is not None:
            sample.update(domain=params("listPeriods")["domain"], var=params("listPeriods")["var"], th=period)
    elif operation == "getForeignTrade":
        sample["tahun"] = find("listForeignTradeYears", "year", "tahun") or sample["tahun"]
    elif operation in {"listCensusTopics", "listCensusAreas"}:
        events = rows("listCensusEvents")
        if events and not any(_field(row, ("id",)) == "sp2020" for row in events):
            sample["kegiatan"] = find("listCensusEvents", "id") or sample["kegiatan"]
    elif operation == "listCensusDatasets":
        topic = find("listCensusTopics", "id")
        if topic is not None:
            sample.update(kegiatan=params("listCensusTopics")["kegiatan"], topik=topic)
    elif operation == "getCensusData":
        dataset = find("listCensusDatasets", "id")
        area = next((_field(row, ("id",)) for row in rows("listCensusAreas") if str(row.get("kode_mfd")) == "11"), None)
        area = area or find("listCensusAreas", "id")
        dataset_event = params("listCensusDatasets").get("kegiatan")
        area_event = params("listCensusAreas").get("kegiatan")
        if dataset is not None and area is not None and dataset_event == area_event:
            sample.update(kegiatan=dataset_event, dataset=dataset, wilayah_sensus=area)
        elif dataset is not None and dataset_event == sample["kegiatan"]:
            sample["dataset"] = dataset
        elif area is not None and area_event == sample["kegiatan"]:
            sample["wilayah_sensus"] = area
    elif operation == "listSimdasiDistricts":
        for row in rows("listSimdasiRegencies"):
            code = _field(row, ("kode_mfd", "kode", "id_wilayah", "id"))
            if code and str(code).isdigit() and str(code).startswith("11") and len(str(code)) == 7:
                sample["parent"] = code
                break
    elif operation == "listSimdasiTablesBySubject":
        subject = find("listSimdasiSubjects", "mms_id", "id_subjek", "id_subject")
        if subject is not None:
            sample.update(wilayah=params("listSimdasiSubjects")["wilayah"], id_subjek=subject)
    elif operation == "getSimdasiTable":
        for row in rows("listSimdasiTables"):
            table, years = row.get("id_tabel"), row.get("ketersediaan_tahun")
            if table and isinstance(years, list) and (valid := [int(y) for y in years if str(y).isdigit()]):
                sample.update(wilayah=params("listSimdasiTables")["wilayah"], id_tabel=table, tahun=max(valid))
                break

    # Upstream IDs often switch between JSON numbers and strings. Convert only samples.
    schema = {p["name"]: p["schema"].get("type") for p in bps_api.OPERATIONS[operation]["parameters"]}

    def validate(values):
        normalized = {k: int(v) if schema[k] == "integer" and str(v).isdigit()
                      else str(v) if schema[k] == "string" else v for k, v in values.items()}
        bps_api.build_request(operation, normalized, "sample-key")
        return normalized

    try:
        return validate(sample)
    except ValueError:
        try:
            return validate(SAMPLES[operation])
        except ValueError:
            return None
