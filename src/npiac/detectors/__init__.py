from .dotnet import DotNetDetector
from .generic import GenericDetector
from .javascript import JavaScriptDetector
from .python import PythonDetector
from .rust import RustDetector

DETECTORS = (
    GenericDetector(),
    PythonDetector(),
    JavaScriptDetector(),
    RustDetector(),
    DotNetDetector(),
)
