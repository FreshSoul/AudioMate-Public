"""AudioMate Tool protocol — base classes, registry, and built-in tools."""

from src.tools.base import (
    Tool,
    ToolContext,
    ToolResult,
    ToolResultStatus,
    ValidationResult,
    PermissionResult,
)
from src.tools.registry import ToolRegistry
from src.tools.waapi_code_tool import (
    WaapiCodeTool,
    extract_code_blocks,
    code_uses_waapi,
    output_has_error,
)
from src.tools.agent_tools import (
    FileAccessTool,
    ListDirectoryTool,
    WriteUserFileTool,
    WriteFileTreeTool,
    AudioAnalysisTool,
    DirectoryLoudnessTool,
    SelectedSourceLoudnessTool,
    NormalizeLoudnessTool,
    DirectoryLoudnessComplianceTool,
    BatchNormalizeDirectoryTool,
    AudioAnomalyTool,
    DirectoryAnomalyTool,
    ProjectStructureValidationTool,
    SourceFileTool,
    ProjectSourceFileTool,
    ImportAudioToSelectedWwiseTool,
)
from src.tools.external_agent_tools import (
    ClaudeCodeAgentTool,
    CodexAgentTool,
    ExternalAgentStatusTool,
)
from src.tools.powershell_tool import PowerShellRunTool
from src.tools.waapi_structured_tools import (
    WaapiBlendContainerAddTrackTool,
    WaapiBlendContainerGetAssignmentsTool,
    WaapiBlendContainerSetAssignmentTool,
    WaapiBatchSetPropertyTool,
    WaapiCallDocumentedReadTool,
    WaapiCallDocumentedWriteTool,
    WaapiCreateBusTool,
    WaapiCreateMusicCueTool,
    WaapiCreateMusicObjectTool,
    WaapiGetBussesTool,
    WaapiFindInProjectExplorerTool,
    WaapiGetAttenuationCurveTool,
    WaapiGetMusicStructureTool,
    WaapiGetObjectsTool,
    WaapiGetPropertyTool,
    WaapiGetPropertyAndReferenceNamesTool,
    WaapiGetSchemaTool,
    WaapiGetSelectedObjectsTool,
    WaapiGetVersionContextTool,
    WaapiProjectSaveTool,
    WaapiResolveHierarchyRootTool,
    WaapiResolveMainBusTool,
    WaapiSetBusPropertyTool,
    WaapiSetAttenuationCurveTool,
    WaapiSetPropertyTool,
    WaapiSetReferenceTool,
    WaapiSetObjectOutputBusTool,
    WaapiSetStateGroupsTool,
    WaapiSetStatePropertiesTool,
    WaapiSoundBankGenerateTool,
    WaapiSoundBankGetInclusionsTool,
    WaapiSoundBankSetInclusionsTool,
    WaapiSoundEngineGetStateTool,
    WaapiSoundEngineGetSwitchTool,
    WaapiSoundEnginePostEventTool,
    WaapiSoundEngineSetRtpcTool,
    WaapiSoundEngineSetStateTool,
    WaapiSoundEngineSetSwitchTool,
    WaapiSoundEngineStopAllTool,
    WaapiSwitchContainerGetAssignmentsTool,
    WaapiSwitchContainerSetAssignmentTool,
)


def create_default_registry() -> ToolRegistry:
    """Build a registry pre-populated with all built-in tools."""
    registry = ToolRegistry()
    registry.register(WaapiCodeTool())
    registry.register(WaapiGetSelectedObjectsTool())
    registry.register(WaapiCallDocumentedReadTool())
    registry.register(WaapiCallDocumentedWriteTool())
    registry.register(WaapiProjectSaveTool())
    registry.register(WaapiGetVersionContextTool())
    registry.register(WaapiResolveHierarchyRootTool())
    registry.register(WaapiGetBussesTool())
    registry.register(WaapiResolveMainBusTool())
    registry.register(WaapiCreateBusTool())
    registry.register(WaapiSetBusPropertyTool())
    registry.register(WaapiSetObjectOutputBusTool())
    registry.register(WaapiSoundEngineGetStateTool())
    registry.register(WaapiSoundEngineGetSwitchTool())
    registry.register(WaapiSoundEnginePostEventTool())
    registry.register(WaapiSoundEngineSetRtpcTool())
    registry.register(WaapiSoundEngineSetStateTool())
    registry.register(WaapiSoundEngineSetSwitchTool())
    registry.register(WaapiSoundEngineStopAllTool())
    registry.register(WaapiSoundBankGetInclusionsTool())
    registry.register(WaapiSoundBankSetInclusionsTool())
    registry.register(WaapiSoundBankGenerateTool())
    registry.register(WaapiBlendContainerGetAssignmentsTool())
    registry.register(WaapiBlendContainerAddTrackTool())
    registry.register(WaapiBlendContainerSetAssignmentTool())
    registry.register(WaapiSwitchContainerGetAssignmentsTool())
    registry.register(WaapiSwitchContainerSetAssignmentTool())
    registry.register(WaapiGetObjectsTool())
    registry.register(WaapiGetPropertyTool())
    registry.register(WaapiSetPropertyTool())
    registry.register(WaapiBatchSetPropertyTool())
    registry.register(WaapiGetSchemaTool())
    registry.register(WaapiGetPropertyAndReferenceNamesTool())
    registry.register(WaapiSetReferenceTool())
    registry.register(WaapiGetAttenuationCurveTool())
    registry.register(WaapiSetAttenuationCurveTool())
    registry.register(WaapiFindInProjectExplorerTool())
    registry.register(WaapiGetMusicStructureTool())
    registry.register(WaapiCreateMusicObjectTool())
    registry.register(WaapiCreateMusicCueTool())
    registry.register(WaapiSetStateGroupsTool())
    registry.register(WaapiSetStatePropertiesTool())
    registry.register(FileAccessTool())
    registry.register(ListDirectoryTool())
    registry.register(WriteUserFileTool())
    registry.register(WriteFileTreeTool())
    registry.register(AudioAnalysisTool())
    registry.register(DirectoryLoudnessTool())
    registry.register(SelectedSourceLoudnessTool())
    registry.register(NormalizeLoudnessTool())
    registry.register(DirectoryLoudnessComplianceTool())
    registry.register(BatchNormalizeDirectoryTool())
    registry.register(AudioAnomalyTool())
    registry.register(DirectoryAnomalyTool())
    registry.register(ProjectStructureValidationTool())
    registry.register(SourceFileTool())
    registry.register(ProjectSourceFileTool())
    registry.register(ImportAudioToSelectedWwiseTool())
    registry.register(ExternalAgentStatusTool())
    registry.register(CodexAgentTool())
    registry.register(ClaudeCodeAgentTool())
    registry.register(PowerShellRunTool())
    return registry
