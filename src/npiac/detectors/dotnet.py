from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import DetectionResult, RepositorySnapshot
from .base import analysis_paths, read_manifest_text


class DotNetDetector:
    def detect(self, snapshot: RepositorySnapshot) -> DetectionResult:
        result = DetectionResult()
        paths = analysis_paths(snapshot)
        projects = sorted(path for path in paths if path.casefold().endswith(".csproj"))
        if not projects and not any(path.casefold().endswith(".cs") for path in paths):
            return result
        result.languages.add("C#")
        result.package_managers.add("NuGet")
        for project in projects:
            try:
                manifest_text = read_manifest_text(snapshot, project)
                if "<!DOCTYPE" in manifest_text.upper() or "<!ENTITY" in manifest_text.upper():
                    raise ET.ParseError("DTD and entity declarations are not allowed")
                root = ET.fromstring(manifest_text)
                sdk = root.attrib.get("Sdk", "")
                if "Web" in sdk:
                    result.frameworks.add("ASP.NET Core")
                for element in root.iter():
                    tag = element.tag.rsplit("}", 1)[-1]
                    if tag == "PackageReference":
                        name = (element.attrib.get("Include") or element.attrib.get("Update") or "").casefold()
                        if name.startswith("microsoft.entityframeworkcore"):
                            result.frameworks.add("Entity Framework Core")
                        database_packages = {
                            "npgsql": "PostgreSQL",
                            "microsoft.data.sqlite": "SQLite",
                            "mysqlconnector": "MySQL",
                            "mongodb.driver": "MongoDB",
                            "stackexchange.redis": "Redis",
                        }
                        if name in database_packages:
                            result.databases.add(database_packages[name])
                        if name in {"xunit", "nunit", "mstest.testframework"}:
                            result.test_frameworks.add({"xunit": "xUnit", "nunit": "NUnit", "mstest.testframework": "MSTest"}[name])
                result.project_names.append((100 if "/" not in project else 60, Path(project).stem))
            except (OSError, ET.ParseError) as exc:
                result.warnings.append(f"Could not parse `{project}`: {type(exc).__name__}.")
        return result
