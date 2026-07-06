import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Crosshair,
  Database,
  FileJson,
  Filter,
  Hand,
  Highlighter,
  CheckCircle2,
  Maximize,
  Maximize2,
  Minimize,
  MessageSquareText,
  Network,
  NotebookPen,
  PanelLeft,
  PanelRight,
  Upload,
  Quote,
  RotateCw,
  RotateCcw,
  Save,
  Search,
  Settings,
  AlertTriangle,
  UserRound,
  X,
  ZoomIn,
  ZoomOut,
  Trash2,
  Edit,
  ChevronLeft,
  ChevronRight,
  Undo,
  Redo,
  FileText,
  Eye,
  EyeOff,
} from "lucide-react";
import { API_BASE, fetchJson } from "../api/client";
import "../styles.css";

type FlexibleRecord = Record<string, any>;

const RECENT_READING_SOURCES_KEY = "koshu_recent_reading_sources";

const emptyFilters = {
  query: "",
  sourceId: "",
  entityType: "",
  relationType: "",
  attitudeType: "",
  polarity: "",
  page: "",
};

const emptyDeskForm = {
  quote: "",
  note: "",
  claimText: "",
  evidenceId: "",
  keyword: "",
  customKeyword: "",
  confidence: "medium",
  entityName: "",
  entityType: "person",
  customEntityType: "",
  subjectEntityId: "",
  subjectName: "",
  subjectType: "person",
  subjectCustomType: "",
  relationType: "",
  customRelationType: "",
  objectEntityId: "",
  objectName: "",
  objectType: "person",
  objectCustomType: "",
  speakerEntityId: "",
  speakerName: "",
  speakerType: "person",
  speakerCustomType: "",
  attitudeType: "",
  customAttitudeType: "",
  polarity: "positive",
  customPolarity: "",
  targetEntityId: "",
  targetName: "",
  targetType: "person",
  targetCustomType: "",
};

function readRecentSourceIds() {
  try {
    const parsed = JSON.parse(window.localStorage?.getItem(RECENT_READING_SOURCES_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((value) => typeof value === "string").slice(0, 8) : [];
  } catch {
    return [];
  }
}

function formatShortDate(value) {
  if (!value) return "undated";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function batchRunRelevantCount(run) {
  const pages = Number(run?.counts?.pages || 0);
  const noPriority = Number(run?.counts?.no_priority_pages || 0);
  return Math.max(0, pages - noPriority);
}

function batchRunLabel(run) {
  const firstSource = run?.sources?.[0] || {};
  const sourceLabel = firstSource.title_original || firstSource.title || run?.source_ids?.[0] || "Batch run";
  const sourceId = run?.source_ids?.[0] ? ` / ${run.source_ids[0]}` : "";
  const pages = run?.counts?.pages || 0;
  const relevant = batchRunRelevantCount(run);
  const approved = run?.counts?.approved_candidates || 0;
  return `${sourceLabel}${sourceId} · ${formatShortDate(run?.created_at)} · ${pages} pages · ${relevant} relevant · ${approved} approved`;
}

function getStatusPercent(status) {
  if (!status) return 0;
  const cleanStatus = status.toLowerCase();
  if (cleanStatus === "completed") return 100;
  if (cleanStatus === "processing") return 2;
  const match = status.match(/(\d+)\s*\/\s*(\d+)/);
  if (match) {
    const idx = parseInt(match[1], 10);
    const total = parseInt(match[2], 10);
    if (total > 0) {
      return Math.round((idx / total) * 100);
    }
  }
  if (cleanStatus.includes("installing") || cleanStatus.includes("loading") || cleanStatus.includes("setting up")) {
    return 5;
  }
  return 0;
}

function Workbench() {
  const [summary, setSummary] = useState(null);
  const [entities, setEntities] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [attitudes, setAttitudes] = useState([]);
  const [editableArtifacts, setEditableArtifacts] = useState([]);
  const [readingSources, setReadingSources] = useState([]);
  const [batchRuns, setBatchRuns] = useState([]);
  const [selectedBatchRunId, setSelectedBatchRunId] = useState("");
  const [batchPages, setBatchPages] = useState([]);
  const [selectedBatchPage, setSelectedBatchPage] = useState(null);
  const [batchMessage, setBatchMessage] = useState("");
  const [ocrEngines, setOcrEngines] = useState([]);
  const [readingPage, setReadingPage] = useState(null);
  const [readingText, setReadingText] = useState("");
  const [deskForm, setDeskForm] = useState(emptyDeskForm);
  const [deskMessage, setDeskMessage] = useState("");
  const [selectedReadingSourceId, setSelectedReadingSourceId] = useState("");
  const [recentReadingSourceIds, setRecentReadingSourceIds] = useState(readRecentSourceIds);
  const [selectedReadingPage, setSelectedReadingPage] = useState(1);
  const [filters, setFilters] = useState(emptyFilters);
  const [activeTab, setActiveTab] = useState("reading");
  const [readingSearchTerm, setReadingSearchTerm] = useState("");
  const [selectedEntity, setSelectedEntity] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState("");
  const [artifactText, setArtifactText] = useState("");
  const [loadedArtifactText, setLoadedArtifactText] = useState("");
  const [editorMessage, setEditorMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [projects, setProjects] = useState(["default"]);
  const [activeProject, setActiveProject] = useState("default");
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [showProjectNoteModal, setShowProjectNoteModal] = useState(false);
  const [projectNoteText, setProjectNoteText] = useState("");
  const [showSourceMetadataModal, setShowSourceMetadataModal] = useState(false);
  const [metaSourceId, setMetaSourceId] = useState("");
  const [metaTitle, setMetaTitle] = useState("");
  const [metaCollection, setMetaCollection] = useState("");
  const [metaCitation, setMetaCitation] = useState("");
  const [metaNotes, setMetaNotes] = useState("");
  const [pageNoteText, setPageNoteText] = useState("");
  const [mergeModalOpen, setMergeModalOpen] = useState(false);
  const [mergeInitialTargetId, setMergeInitialTargetId] = useState("");
  const [globalOcrResults, setGlobalOcrResults] = useState([]);
  const [globalOcrSearching, setGlobalOcrSearching] = useState(false);
  const [isSearchFocused, setIsSearchFocused] = useState(false);

  const [entityTypes, setEntityTypes] = useState(() => {
    try {
      const saved = localStorage.getItem("koshu_entity_types");
      return saved ? JSON.parse(saved) : ["person", "place", "organization", "group", "event", "document"];
    } catch (e) {
      return ["person", "place", "organization", "group", "event", "document"];
    }
  });
  const [relationTypes, setRelationTypes] = useState(() => {
    try {
      const saved = localStorage.getItem("koshu_relation_types");
      return saved ? JSON.parse(saved) : ["spouse", "parent", "child", "relative", "colleague", "employer", "employee_of", "member_of", "founder_of", "advisor", "student", "acquaintance", "opponent", "ally"];
    } catch (e) {
      return ["spouse", "parent", "child", "relative", "colleague", "employer", "employee_of", "member_of", "founder_of", "advisor", "student", "acquaintance", "opponent", "ally"];
    }
  });

  useEffect(() => {
    localStorage.setItem("koshu_entity_types", JSON.stringify(entityTypes));
  }, [entityTypes]);

  useEffect(() => {
    localStorage.setItem("koshu_relation_types", JSON.stringify(relationTypes));
  }, [relationTypes]);

  // States for hand-editing spreadsheet views
  const [editingEntity, setEditingEntity] = useState(null);
  const [editingRelationship, setEditingRelationship] = useState(null);
  const [editingAttitude, setEditingAttitude] = useState(null);

  // CRUD callback handlers for hand-editing
  async function handleUpdateEntity(entityData) {
    try {
      setLoading(true);
      await fetchJson("/api/v1/evidence/entities", {
        method: "PUT",
        body: JSON.stringify(entityData),
      });
      setEditingEntity(null);
      await refreshAll();
    } catch (err) {
      alert("Failed to update entity: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleMergeEntities(targetEntityId, sourceEntityIds) {
    const confirm = window.confirm("Are you sure you want to merge these entities? This action will combine the nodes permanently.");
    if (!confirm) return;
    try {
      setLoading(true);
      await fetchJson("/api/v1/evidence/entities/merge", {
        method: "POST",
        body: JSON.stringify({
          target_entity_id: targetEntityId,
          source_entity_ids: sourceEntityIds,
        }),
      });
      setMergeModalOpen(false);
      await refreshAll();
      alert("Entities merged successfully!");
    } catch (err) {
      alert("Failed to merge entities: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteEntity(entityId, sourceId = null) {
    const confirm = window.confirm("Are you sure you want to delete this entity? This will clean up its mentions, relationships, and attitudes.");
    if (!confirm) return;
    try {
      setLoading(true);
      const query = sourceId ? `?entity_id=${entityId}&source_id=${sourceId}` : `?entity_id=${entityId}`;
      await fetchJson(`/api/v1/evidence/entities${query}`, {
        method: "DELETE",
      });
      await refreshAll();
    } catch (err) {
      alert("Failed to delete entity: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleUpdateRelationship(relData) {
    try {
      setLoading(true);
      await fetchJson("/api/v1/evidence/relationships", {
        method: "PUT",
        body: JSON.stringify(relData),
      });
      setEditingRelationship(null);
      await refreshAll();
    } catch (err) {
      alert("Failed to update relationship: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteRelationship(relId, sourceId) {
    const confirm = window.confirm("Are you sure you want to delete this relationship claim?");
    if (!confirm) return;
    try {
      setLoading(true);
      await fetchJson(`/api/v1/evidence/relationships?relationship_id=${relId}&source_id=${sourceId}`, {
        method: "DELETE",
      });
      await refreshAll();
    } catch (err) {
      alert("Failed to delete relationship: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleUpdateAttitude(attData) {
    try {
      setLoading(true);
      await fetchJson("/api/v1/evidence/attitudes", {
        method: "PUT",
        body: JSON.stringify(attData),
      });
      setEditingAttitude(null);
      await refreshAll();
    } catch (err) {
      alert("Failed to update attitude claim: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteAttitude(attId, sourceId) {
    const confirm = window.confirm("Are you sure you want to delete this attitude claim?");
    if (!confirm) return;
    try {
      setLoading(true);
      await fetchJson(`/api/v1/evidence/attitudes?attitude_id=${attId}&source_id=${sourceId}`, {
        method: "DELETE",
      });
      await refreshAll();
    } catch (err) {
      alert("Failed to delete attitude: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  const fileMode = window.location.protocol === "file:";

  useEffect(() => {
    loadProjects();
    refreshAll();
  }, []);


  useEffect(() => {
    const q = filters.query || "";
    if (!q.trim()) {
      setGlobalOcrResults([]);
      return;
    }
    setGlobalOcrSearching(true);
    const timer = setTimeout(async () => {
      try {
        const results = await fetchJson(`/api/v1/reading/search-ocr?q=${encodeURIComponent(q)}`);
        setGlobalOcrResults(results || []);
      } catch (err) {
        console.error("Global OCR search failed:", err);
      } finally {
        setGlobalOcrSearching(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [filters.query]);

  async function loadProjectNote(projectId) {
    try {
      const res = await fetchJson(`/api/v1/projects/${projectId}/note`);
      setProjectNoteText(res.note || "");
    } catch (err) {
      console.error("Failed to load project note:", err);
    }
  }

  async function saveProjectNote(projectId, note) {
    try {
      setLoading(true);
      await fetchJson(`/api/v1/projects/${projectId}/note`, {
        method: "PUT",
        body: JSON.stringify({ note })
      });
      setShowProjectNoteModal(false);
    } catch (err) {
      alert("Failed to save project note: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleOpenSourceMetadata(sourceId) {
    try {
      setLoading(true);
      const artifact = await fetchJson(`/api/v1/extraction-artifacts/${sourceId}`);
      const srcRecord = readingSources.find(s => s.source_id === sourceId) || {};
      
      setMetaSourceId(sourceId);
      setMetaTitle(srcRecord.title_original || srcRecord.title || artifact.title || sourceId);
      setMetaCollection(srcRecord.collection || artifact.collection || "");
      setMetaCitation(srcRecord.citation || artifact.citation || "");
      setMetaNotes(artifact.notes || srcRecord.notes || "");
      
      setShowSourceMetadataModal(true);
    } catch (err) {
      alert("Failed to load source metadata: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveSourceMetadata() {
    if (!metaTitle.trim()) {
      alert("Source title is required");
      return;
    }
    
    try {
      setLoading(true);
      await fetchJson(`/api/v1/sources/${metaSourceId}/metadata`, {
        method: "PUT",
        body: JSON.stringify({
          title: metaTitle.trim(),
          title_original: metaTitle.trim(),
          collection: metaCollection.trim(),
          citation: metaCitation.trim(),
          notes: metaNotes
        })
      });
      
      setShowSourceMetadataModal(false);
      
      const readingData = await fetchJson("/api/v1/reading/sources");
      setReadingSources(readingData);
      if (selectedReadingSourceId === metaSourceId) {
        await loadReadingPage(metaSourceId, selectedReadingPage);
        await loadArtifact(metaSourceId);
      }
    } catch (err) {
      alert("Failed to save source metadata: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function savePageNoteText(sourceId, page, note) {
    if (!sourceId || !page) return;
    try {
      await fetchJson(`/api/v1/reading/sources/${sourceId}/pages/${page}/note`, {
        method: "PUT",
        body: JSON.stringify({ note })
      });
      await loadReadingPage(sourceId, page);
    } catch (err) {
      alert("Failed to save page note: " + err.message);
    }
  }

  async function loadProjects() {
    try {
      const data = await fetchJson("/api/v1/projects");
      setProjects(data.projects);
      setActiveProject(data.active);
      loadProjectNote(data.active);
    } catch (err) {
      console.error("Failed to load projects", err);
    }
  }

  async function switchProject(projectId) {
    try {
      setLoading(true);
      await fetchJson("/api/v1/projects/active", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
      });
      setActiveProject(projectId);
      loadProjectNote(projectId);
      setSelectedReadingSourceId("");
      setSelectedBatchRunId("");
      setSelectedArtifactId("");
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateProject() {
    if (!newProjectName.trim()) return;
    try {
      const res = await fetchJson("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify({ name: newProjectName }),
      });
      setShowNewProjectModal(false);
      setNewProjectName("");
      const data = await fetchJson("/api/v1/projects");
      setProjects(data.projects);
      await switchProject(res.project_id);
    } catch (err) {
      alert(`Failed to create project: ${err.message}`);
    }
  }

  async function deleteProject(projectId) {
    if (projectId === "default") return;
    const confirmed = window.confirm(
      `Are you sure you want to delete the project "${projectId}"?\\n\\nThis will archive the project workspace and remove it from this list. The raw files and JSON extractions on disk will remain safely archived.`
    );
    if (!confirmed) return;
    
    try {
      setLoading(true);
      await fetchJson(`/api/v1/projects/${projectId}`, {
        method: "DELETE",
      });
      const data = await fetchJson("/api/v1/projects");
      setProjects(data.projects);
      await switchProject("default");
    } catch (err) {
      setError(`Failed to delete project: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleRenameProject() {
    if (activeProject === "default") {
      alert("Cannot rename the default project.");
      return;
    }
    const newName = prompt("Enter new project name:", activeProject);
    if (!newName || !newName.trim() || newName === activeProject) return;

    try {
      setLoading(true);
      const res = await fetchJson(`/api/v1/projects/${activeProject}/rename`, {
        method: "POST",
        body: JSON.stringify({ name: newName.trim() })
      });
      const data = await fetchJson("/api/v1/projects");
      setProjects(data.projects);
      setActiveProject(res.project_id);
    } catch (err) {
      alert(`Failed to rename project: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleRenameSource(sourceId, currentTitle) {
    const newTitle = prompt("Enter new source title:", currentTitle);
    if (!newTitle || !newTitle.trim() || newTitle === currentTitle) return;

    try {
      setLoading(true);
      await fetchJson(`/api/v1/sources/${sourceId}/metadata`, {
        method: "PUT",
        body: JSON.stringify({
          title: newTitle.trim(),
          title_original: newTitle.trim()
        })
      });
      const readingData = await fetchJson("/api/v1/reading/sources");
      setReadingSources(readingData);
      if (selectedReadingSourceId === sourceId) {
        await loadReadingPage(sourceId, selectedReadingPage);
      }
    } catch (err) {
      alert(`Failed to rename source: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteSource(sourceId) {
    const sourceName = readingSources.find(s => s.source_id === sourceId)?.title_original || sourceId;
    const confirmed = window.confirm(
      `WARNING: Are you sure you want to permanently delete the source "${sourceName}"?\n\n` +
      `This will completely delete the PDF file, raw OCR data, corrected transcriptions, and all metadata for this source from your disk. This action is permanent and cannot be undone.`
    );
    if (!confirmed) return;
    
    try {
      setLoading(true);
      const res = await fetchJson(`/api/v1/reading/sources/${sourceId}`, {
        method: "DELETE"
      });
      alert(res.message || "Source deleted successfully.");
      
      // Update reading sources list
      const updatedSources = readingSources.filter(s => s.source_id !== sourceId);
      setReadingSources(updatedSources);
      
      // Reset selected source
      setSelectedReadingSourceId("");
      setReadingPage(null);
      setReadingText("");
      
      await refreshAll();
    } catch (err) {
      alert("Failed to delete source: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!selectedArtifactId) return;
    loadArtifact(selectedArtifactId);
  }, [selectedArtifactId]);

  useEffect(() => {
    if (!selectedReadingSourceId) return;
    loadReadingPage(selectedReadingSourceId, selectedReadingPage);
  }, [selectedReadingSourceId, selectedReadingPage]);

  useEffect(() => {
    if (!selectedBatchRunId) return;
    loadBatchPages(selectedBatchRunId);
  }, [selectedBatchRunId]);

  useEffect(() => {
    const hasActiveRun = batchRuns.some(run => 
      run.status === "processing" || 
      (run.status && (
        run.status.startsWith("Installing") || 
        run.status.startsWith("Loading") || 
        run.status.startsWith("Running") || 
        run.status.startsWith("Text")
      ))
    );

    if (!hasActiveRun) return;

    const interval = setInterval(async () => {
      try {
        const batchRunData = await fetchJson("/api/v1/batches/biographies/runs");
        setBatchRuns(batchRunData);
        if (selectedBatchRunId) {
          await loadBatchPages(selectedBatchRunId);
        }
      } catch (err) {
        console.error("Polling batch runs failed:", err);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [batchRuns, selectedBatchRunId]);

  async function refreshAll() {
    setLoading(true);
    setError("");
    try {
      const [readingData, batchRunData, ocrEngineData] = await Promise.all([
        fetchJson("/api/v1/reading/sources"),
        fetchJson("/api/v1/batches/biographies/runs").catch(() => []),
        fetchJson("/api/v1/ocr/engines").catch(() => []),
      ]);
      setReadingSources(readingData);
      setBatchRuns(batchRunData);
      setOcrEngines(ocrEngineData || []);
      setSelectedBatchRunId((current) => current || batchRunData[0]?.run_id || "");
      setSelectedReadingSourceId((current) => {
        if (current) return current;
        const recentSource = recentReadingSourceIds.map((sourceId) => readingData.find((source) => source.source_id === sourceId)).find(Boolean);
        return recentSource?.source_id || readingData.find((source) => source.ocr_pages?.length)?.source_id || "";
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadArtifact(sourceId) {
    setEditorMessage("");
    setError("");
    try {
      const artifact = await fetchJson(`/api/v1/extraction-artifacts/${sourceId}`);
      const formatted = `${JSON.stringify(artifact, null, 2)}\n`;
      setArtifactText(formatted);
      setLoadedArtifactText(formatted);
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadReadingPage(sourceId, page) {
    setDeskMessage("");
    setError("");
    try {
      const pageData = await fetchJson(`/api/v1/reading/sources/${sourceId}/pages/${page}`);
      setReadingPage(pageData);
      setReadingText(pageData.ocr.corrected_text || pageData.ocr.raw_text || "");
      setPageNoteText(pageData.page_note || "");
      setDeskForm((current) => ({ ...current, quote: "", keyword: "", customKeyword: "", note: "", claimText: "", evidenceId: "" }));
      rememberReadingSource(sourceId);
    } catch (err) {
      setReadingPage(null);
      setReadingText("");
      setError(err.message);
    }
  }

  async function saveArtifact() {
    setEditorMessage("");
    setError("");
    let parsed;
    try {
      parsed = JSON.parse(artifactText);
    } catch (err) {
      setEditorMessage(`JSON parse error: ${err.message}`);
      return;
    }
    try {
      const result = await fetchJson(`/api/v1/extraction-artifacts/${selectedArtifactId}`, {
        method: "PUT",
        body: JSON.stringify(parsed),
      });
      setEditorMessage(result.message);
      await refreshAll();
      await loadArtifact(selectedArtifactId);
    } catch (err) {
      setEditorMessage(err.message);
    }
  }

  async function saveOcrReview(provenance: FlexibleRecord = {}) {
    if (!selectedReadingSourceId || !selectedReadingPage) return;
    setDeskMessage("");
    setError("");
    try {
      const result = await fetchJson(`/api/v1/reading/sources/${selectedReadingSourceId}/pages/${selectedReadingPage}/ocr-review`, {
        method: "PUT",
        body: JSON.stringify({
          text: readingText,
          notes: deskForm.note,
          reviewer: "local researcher",
          status: "reviewed",
          original_ocr_page_json: provenance.ocr_page_json || "",
          region_ocr_json: provenance.region_ocr_json || "",
          region: provenance.region || {},
          region_id: provenance.region_id || "",
          debug: import.meta.env.DEV,
        }),
      });
      setDeskMessage(result.message);
      await refreshAll();
      await loadReadingPage(selectedReadingSourceId, selectedReadingPage);
      if (
        selectedBatchRunId
        && selectedBatchPage?.source_id === selectedReadingSourceId
        && Number(selectedBatchPage?.page) === Number(selectedReadingPage)
      ) {
        await syncBatchPageOcr(selectedBatchRunId, selectedReadingSourceId, selectedReadingPage);
      }
      return result;
    } catch (err) {
      setDeskMessage(err.message);
      return null;
    }
  }

  async function saveDeskEvidence(kind, overrides: FlexibleRecord = {}, pageOverride = null) {
    const targetPage = pageOverride || selectedReadingPage;
    if (!selectedReadingSourceId || !targetPage) return;
    setDeskMessage("");
    const formValues = { ...deskForm, ...overrides } as typeof emptyDeskForm & FlexibleRecord;
    const relationType = formValues.customRelationType || formValues.relationType;
    const attitudeType = formValues.customAttitudeType || formValues.attitudeType;
    const polarity = formValues.customPolarity || formValues.polarity;
    const payload = {
      kind,
      quote: formValues.quote,
      note: formValues.note,
      confidence: formValues.confidence,
      evidence_id: formValues.evidenceId,
      requires_evidence: kind !== "quote" && kind !== "note",
      ocr_page_json: formValues.ocr_page_json || formValues.ocrPageJson || "",
      corrected_ocr_page_json: formValues.corrected_ocr_page_json || formValues.correctedOcrPageJson || "",
      region_ocr_json: formValues.region_ocr_json || formValues.regionOcrJson || "",
      region: formValues.region || {},
      region_id: formValues.region_id || formValues.regionId || "",
      keyword: formValues.customKeyword || formValues.keyword,
      claim: {
        text: formValues.claimText || formValues.quote,
      },
      entity: {
        name: formValues.entityName || formValues.quote,
        entity_type: kind === "place" ? "place" : formValues.customEntityType || formValues.entityType,
      },
      relationship: {
        relation_type: relationType,
        subject: {
          entity_id: formValues.subjectEntityId,
          name: formValues.subjectName,
          entity_type: formValues.subjectCustomType || formValues.subjectType,
        },
        object: {
          entity_id: formValues.objectEntityId,
          name: formValues.objectName,
          entity_type: formValues.objectCustomType || formValues.objectType,
        },
      },
      attitude: {
        attitude_type: attitudeType,
        polarity,
        speaker: {
          entity_id: formValues.speakerEntityId,
          name: formValues.speakerName,
          entity_type: formValues.speakerCustomType || formValues.speakerType,
        },
        target: {
          entity_id: formValues.targetEntityId,
          name: formValues.targetName,
          entity_type: formValues.targetCustomType || formValues.targetType,
        },
      },
    };
    try {
      const result = await fetchJson(`/api/v1/reading/sources/${selectedReadingSourceId}/pages/${targetPage}/evidence`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setDeskMessage(result.message);
      await refreshAll();
      await loadReadingPage(selectedReadingSourceId, selectedReadingPage);
      return result;
    } catch (err) {
      setDeskMessage(err.message);
      return { ok: false, error: err.message };
    }
  }

  async function saveDeskCandidate(candidate) {
    if (!selectedReadingSourceId || !selectedReadingPage) return;
    const kind = candidate.kind || candidate.candidate_type;
    const quote = candidate.quote || candidate.label || deskForm.quote;
    const note = candidate.note || deskForm.note;
    const candidateRelationship = candidate.relationship || {};
    const candidateAttitude = candidate.attitude || {};
    const candidateEntity = candidate.entity || {};
    const payload = {
      kind,
      quote,
      note,
      evidence_id: candidate.evidence_id || "",
      requires_evidence: true,
      ocr_page_json: candidate.provenance?.ocr_page_json || "",
      corrected_ocr_page_json: candidate.provenance?.corrected_ocr_page_json || "",
      region: candidate.provenance?.region || {},
      region_id: candidate.provenance?.region_id || "",
      confidence: candidate.confidence || deskForm.confidence || "medium",
      keyword: candidate.keyword || candidate.label || quote,
      claim: {
        text: candidate.claim?.text || candidate.label || quote,
      },
      entity: {
        entity_id: candidateEntity.entity_id || candidate.entity_id || "",
        name: candidateEntity.name || candidate.entity_name || candidate.label || quote,
        entity_type: kind === "place" ? "place" : candidateEntity.entity_type || candidate.entity_type || deskForm.entityType || "person",
      },
      relationship: {
        relation_type: candidateRelationship.relation_type || deskForm.customRelationType || deskForm.relationType,
        subject: {
          entity_id: candidateRelationship.subject?.entity_id || deskForm.subjectEntityId,
          name: candidateRelationship.subject?.name || deskForm.subjectName,
          entity_type: candidateRelationship.subject?.entity_type || deskForm.subjectCustomType || deskForm.subjectType,
        },
        object: {
          entity_id: candidateRelationship.object?.entity_id || deskForm.objectEntityId,
          name: candidateRelationship.object?.name || deskForm.objectName,
          entity_type: candidateRelationship.object?.entity_type || deskForm.objectCustomType || deskForm.objectType,
        },
      },
      attitude: {
        attitude_type: candidateAttitude.attitude_type || deskForm.customAttitudeType || deskForm.attitudeType,
        polarity: candidateAttitude.polarity || deskForm.customPolarity || deskForm.polarity,
        speaker: {
          entity_id: candidateAttitude.speaker?.entity_id || deskForm.speakerEntityId,
          name: candidateAttitude.speaker?.name || deskForm.speakerName,
          entity_type: candidateAttitude.speaker?.entity_type || deskForm.speakerCustomType || deskForm.speakerType,
        },
        target: {
          entity_id: candidateAttitude.target?.entity_id || deskForm.targetEntityId,
          name: candidateAttitude.target?.name || deskForm.targetName,
          entity_type: candidateAttitude.target?.entity_type || deskForm.targetCustomType || deskForm.targetType,
        },
      },
    };
    try {
      const result = await fetchJson(`/api/v1/reading/sources/${selectedReadingSourceId}/pages/${selectedReadingPage}/evidence`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setDeskMessage(result.message);
      await refreshAll();
      await loadReadingPage(selectedReadingSourceId, selectedReadingPage);
    } catch (err) {
      setDeskMessage(err.message);
    }
  }

  function updateFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  function updateDeskForm(name, value) {
    setDeskForm((current) => ({ ...current, [name]: value }));
  }

  function rememberReadingSource(sourceId) {
    if (!sourceId) return;
    setRecentReadingSourceIds((current) => {
      const next = [sourceId, ...current.filter((item) => item !== sourceId)].slice(0, 8);
      window.localStorage?.setItem(RECENT_READING_SOURCES_KEY, JSON.stringify(next));
      return next;
    });
  }

  function selectReadingSource(sourceId) {
    const nextSource = readingSources.find((source) => source.source_id === sourceId);
    setSelectedReadingSourceId(sourceId);
    setSelectedReadingPage(nextSource?.ocr_pages?.[0] || 1);
    rememberReadingSource(sourceId);
  }

  function jumpToReadingPage(sourceId, pageNumber, highlightText = "") {
    setSelectedReadingSourceId(sourceId);
    setSelectedReadingPage(pageNumber);
    rememberReadingSource(sourceId);
    if (highlightText) {
      setReadingSearchTerm(highlightText);
    }
    setActiveTab("reading");
  }

  async function importReadingPdf(file) {
    if (!file) return "";
    const response = await fetch(`${API_BASE}/api/v1/reading/import-pdf`, {
      method: "POST",
      headers: {
        "Content-Type": file.name.toLowerCase().endsWith('.zip') ? "application/zip" : "application/pdf",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
    if (!response.ok) {
      let message = await response.text();
      try {
        const parsed = JSON.parse(message);
        message = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail, null, 2);
      } catch {
        // Keep raw text.
      }
      throw new Error(message);
    }
    const result = await response.json();
    await refreshAll();
    const source = result.source;
    setSelectedReadingSourceId(source.source_id);
    setSelectedReadingPage(source.ocr_pages?.[0] || 1);
    rememberReadingSource(source.source_id);
    const checksum = source.checksum_sha256 ? ` Checksum: ${source.checksum_sha256.slice(0, 16)}...` : "";
    const pages = source.page_count || source.pdf_status?.page_count ? ` Pages: ${source.page_count || source.pdf_status.page_count}.` : "";
    return `${result.message} Source ID: ${source.source_id}.${pages}${checksum}`;
  }

  async function createBatchRun(sourceId = "raw_ee2029d2f4ef") {
    setBatchMessage("");
    setError("");
    if (!sourceId) {
      setBatchMessage("Choose a source before starting batch review.");
      return;
    }
    try {
      const result = await fetchJson("/api/v1/batches/biographies/runs", {
        method: "POST",
        body: JSON.stringify({ source_id: sourceId, run_ocr: true }),
      });
      setBatchMessage(result.message);
      await refreshAll();
      setSelectedBatchRunId(result.run.run_id);
      setSelectedBatchPage(null);
      setActiveTab("batch");
      await loadBatchPages(result.run.run_id);
    } catch (err) {
      setBatchMessage(err.message);
    }
  }

  async function loadBatchPages(runId, query: Record<string, string | number | boolean | null | undefined> = {}) {
    if (!runId) return;
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    });
    const suffix = params.toString() ? `?${params.toString()}` : "";
    try {
      const pages = await fetchJson(`/api/v1/batches/biographies/runs/${runId}/pages${suffix}`);
      setBatchPages(pages);
      if (pages.length > 0 && !selectedBatchPage) {
        await loadBatchPage(runId, pages[0].source_id, pages[0].page);
      }
    } catch (err) {
      setBatchMessage(err.message);
    }
  }

  async function loadBatchPage(runId, sourceId, page) {
    setBatchMessage("");
    try {
      const packet = await fetchJson(`/api/v1/batches/biographies/runs/${runId}/pages/${sourceId}/${page}`);
      setSelectedBatchPage(packet);
    } catch (err) {
      setBatchMessage(err.message);
    }
  }

  async function saveBatchPage(packet, options: { quiet?: boolean } = {}) {
    if (!packet?.run_id || !packet?.source_id || !packet?.page) return null;
    try {
      const result = await fetchJson(`/api/v1/batches/biographies/runs/${packet.run_id}/pages/${packet.source_id}/${packet.page}`, {
        method: "PUT",
        body: JSON.stringify({
          ocr_text: packet.ocr_text,
          ocr_status: packet.ocr_status,
          review_status: packet.review_status,
          quote_candidates: packet.quote_candidates,
          structured_candidates: packet.structured_candidates,
        }),
      });
      setSelectedBatchPage(result.page);
      if (!options.quiet) setBatchMessage(result.message);
      await loadBatchPages(packet.run_id);
      return result;
    } catch (err) {
      setBatchMessage(err.message);
      return null;
    }
  }

  async function syncBatchPageOcr(runId, sourceId, page) {
    if (!runId || !sourceId || !page) return null;
    try {
      const result = await fetchJson(`/api/v1/batches/biographies/runs/${runId}/pages/${sourceId}/${page}/sync-ocr`, {
        method: "POST",
      });
      setSelectedBatchPage(result.page);
      setBatchMessage(result.message);
      await loadBatchPages(runId);
      return result;
    } catch (err) {
      setBatchMessage(err.message);
      return null;
    }
  }

  async function promoteBatchRun(runId, sourceId, page, packet = null) {
    if (!runId) return;
    try {
      if (packet) {
        const saved = await saveBatchPage(packet, { quiet: true });
        if (!saved) return;
      }
      const result = await fetchJson(`/api/v1/batches/biographies/runs/${runId}/promote`, {
        method: "POST",
        body: JSON.stringify({ source_id: sourceId || "", page: page || null }),
      });
      const skipped = result.skipped ? ` · ${result.skipped} skipped` : "";
      setBatchMessage(`${result.message} ${JSON.stringify(result.promoted || {})}${skipped}`);
      await refreshAll();
      await loadBatchPages(runId);
      if (sourceId && page) await loadBatchPage(runId, sourceId, page);
    } catch (err) {
      setBatchMessage(err.message);
    }
  }

  async function deleteBatchRun(runId) {
    if (!runId) return;
    const confirmed = window.confirm("Delete this provisional batch run? Approved items already promoted to evidence JSON will not be removed.");
    if (!confirmed) return;
    try {
      const result = await fetchJson(`/api/v1/batches/biographies/runs/${runId}`, { method: "DELETE" });
      const nextRuns = result.runs || [];
      const nextRunId = nextRuns[0]?.run_id || "";
      setBatchRuns(nextRuns);
      setSelectedBatchRunId(nextRunId);
      setSelectedBatchPage(null);
      setBatchPages([]);
      setBatchMessage(result.message);
      if (nextRunId) await loadBatchPages(nextRunId);
    } catch (err) {
      setBatchMessage(err.message);
    }
  }

  async function openEntity(entityId) {
    setError("");
    try {
      setSelectedEntity(await fetchJson(`/api/v1/evidence/entities/${entityId}`));
    } catch (err) {
      setError(err.message);
    }
  }

  async function openEvidence(evidenceId) {
    setError("");
    try {
      setEvidence(await fetchJson(`/api/v1/evidence/quotes/${evidenceId}`));
    } catch (err) {
      setError(err.message);
    }
  }

  const filteredEntities = useMemo(() => {
    return entities.filter((entity) => {
      if (filters.entityType && entity.entity_type !== filters.entityType) return false;
      if (filters.sourceId && !entity.source_ids?.includes(filters.sourceId)) return false;
      return matchesQuery(entity, filters.query);
    });
  }, [entities, filters]);

  const filteredRelationships = useMemo(() => {
    return relationships.filter((claim) => {
      if (filters.sourceId && claim.source_id !== filters.sourceId) return false;
      if (filters.relationType && claim.relation_type !== filters.relationType) return false;
      if (filters.page && String(claim.page) !== String(filters.page)) return false;
      return matchesQuery(claim, filters.query);
    });
  }, [relationships, filters]);

  const filteredAttitudes = useMemo(() => {
    return attitudes.filter((claim) => {
      if (filters.sourceId && claim.source_id !== filters.sourceId) return false;
      if (filters.attitudeType && claim.attitude_type !== filters.attitudeType) return false;
      if (filters.polarity && claim.polarity !== filters.polarity) return false;
      if (filters.page && String(claim.page) !== String(filters.page)) return false;
      return matchesQuery(claim, filters.query);
    });
  }, [attitudes, filters]);

  const selectedReadingSource = readingSources.find((source) => source.source_id === selectedReadingSourceId);
  const recentReadingSources = recentReadingSourceIds
    .map((sourceId) => readingSources.find((source) => source.source_id === sourceId))
    .filter(Boolean);
  const activeCount = {
    reading: selectedReadingSource?.ocr_pages?.length || 0,
    interactive_desk: entities.length,
    batch: batchPages.length,
    entities: filteredEntities.length,
    relationships: filteredRelationships.length,
    attitudes: filteredAttitudes.length,
    editor: editableArtifacts.length,
  }[activeTab];

  return (
    <main className="appShell sidebar-collapsed">

      <section className="workspace">
        <header className="topbar">
          <form className="searchBox" onSubmit={(event) => event.preventDefault()} style={{ position: "relative" }}>
            <Search size={18} />
            <input
              value={filters.query}
              onChange={(event) => updateFilter("query", event.target.value)}
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => setTimeout(() => setIsSearchFocused(false), 200)}
              placeholder=""
            />
            {isSearchFocused && (filters.query || "").trim() && (
              <div className="globalOcrDropdown" style={{
                position: "absolute",
                top: "100%",
                left: 0,
                right: 0,
                background: "var(--bg-surface-elevated, #fff)",
                border: "1px solid var(--border-color)",
                borderRadius: "6px",
                boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
                zIndex: 1000,
                maxHeight: "320px",
                overflowY: "auto",
                marginTop: "4px",
                padding: "8px 0"
              }}>
                <div style={{ padding: "4px 12px", fontSize: "0.75rem", color: "var(--text-secondary)", borderBottom: "1px solid var(--border-color)", fontWeight: 600 }}>
                  OCR Keyword Matches ({globalOcrResults.length})
                </div>
                {globalOcrSearching && <div style={{ padding: "8px 12px", fontSize: "0.85rem", color: "var(--text-secondary)" }}>Searching document text...</div>}
                {!globalOcrSearching && globalOcrResults.length === 0 && (
                  <div style={{ padding: "8px 12px", fontSize: "0.85rem", color: "var(--text-secondary)" }}>No text occurrences found.</div>
                )}
                {!globalOcrSearching && globalOcrResults.map((item, idx) => (
                  <button
                    key={`${item.source_id}_${item.page}_${idx}`}
                    onMouseDown={() => {
                      setReadingSearchTerm(filters.query);
                      setActiveTab("reading");
                      setSelectedReadingSourceId(item.source_id);
                      setSelectedReadingPage(item.page);
                    }}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      background: "transparent",
                      border: "none",
                      padding: "8px 12px",
                      cursor: "pointer",
                      display: "block",
                      borderBottom: "1px solid var(--border-color-light, #f5f5f5)",
                      transition: "background 0.2s"
                    }}
                    onMouseOver={(e) => e.currentTarget.style.background = "var(--bg-surface)"}
                    onMouseOut={(e) => e.currentTarget.style.background = "transparent"}
                  >
                    <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-primary)" }}>
                      {item.source_title || item.source_id} (Page {item.page})
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: 2, fontStyle: "italic", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {item.snippet}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </form>
          <div className="projectSelector" style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto", marginRight: 16 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}>Project:</span>
            <select
              value={activeProject}
              onChange={(e) => {
                if (e.target.value === "__new__") {
                  setShowNewProjectModal(true);
                } else {
                  switchProject(e.target.value);
                }
              }}
              style={{
                background: "var(--bg-surface-elevated, #fff)",
                border: "1px solid var(--border-color)",
                borderRadius: 6,
                padding: "4px 8px",
                fontSize: 13,
                fontWeight: 500,
                color: "var(--text-primary)",
                cursor: "pointer",
                outline: "none",
              }}
            >
              {projects.map((p) => (
                <option key={p} value={p}>
                  {p === "default" ? "Default Project" : p}
                </option>
              ))}
              <option value="__new__">+ New Project...</option>
            </select>
            {activeProject !== "default" && (
              <>
                <button
                  onClick={() => setShowProjectNoteModal(true)}
                  title="View/Edit Project Notes & Research Context"
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--text-secondary)",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: 4,
                    borderRadius: 4,
                    transition: "background 0.2s",
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = "var(--bg-surface-elevated)"}
                  onMouseOut={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <NotebookPen size={16} />
                </button>
                <button
                  onClick={handleRenameProject}
                  title="Rename current project"
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--text-secondary)",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: 4,
                    borderRadius: 4,
                    transition: "background 0.2s",
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = "var(--bg-surface-elevated)"}
                  onMouseOut={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <Edit size={16} />
                </button>
                <button
                  onClick={() => deleteProject(activeProject)}
                  title="Delete/Archive current project"
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "#ef4444",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: 4,
                    borderRadius: 4,
                    transition: "background 0.2s",
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = "rgba(239, 68, 68, 0.1)"}
                  onMouseOut={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <Trash2 size={16} />
                </button>
              </>
            )}
          </div>
          <span className="recordCount" style={{ marginLeft: 0 }}>{activeCount} visible</span>
        </header>

        {fileMode && (
          <div className="warningBanner">
            The workbench is open from a file path. Run it at http://127.0.0.1:5173/ so the Reading Desk can talk to the local API.
          </div>
        )}
        {error && <div className="errorBanner">{error}</div>}

                <div className="modeTabs" role="tablist" aria-label="Evidence views">
          <TabButton active={activeTab === "reading"} icon={<NotebookPen size={16} />} onClick={() => setActiveTab("reading")}>
            Reading Desk
          </TabButton>
          <TabButton active={activeTab === "batch"} icon={<Database size={16} />} onClick={() => setActiveTab("batch")}>
            Batch Review
          </TabButton>
        </div>

                {activeTab === "reading" && (
          <ReadingDesk
            sources={readingSources}
            recentSources={recentReadingSources}
            source={selectedReadingSource}
            pageData={readingPage}
            page={selectedReadingPage}
            text={readingText}
            ocrEngines={ocrEngines}
            onSourceChange={selectReadingSource}
            onPageChange={setSelectedReadingPage}
            onTextChange={setReadingText}
            onSaveOcr={saveOcrReview}
            onSaveEvidence={saveDeskEvidence}
            onImportPdf={importReadingPdf}
            onRenameSource={handleOpenSourceMetadata}
            onDeleteSource={handleDeleteSource}
            onReloadPage={() => loadReadingPage(selectedReadingSourceId, selectedReadingPage)}
            searchTerm={readingSearchTerm}
            setSearchTerm={setReadingSearchTerm}
            pageNoteText={pageNoteText}
            onPageNoteTextChange={setPageNoteText}
            onSavePageNote={savePageNoteText}
          />
        )}

        {activeTab === "batch" && (
          <BatchReview
            runs={batchRuns}
            selectedRunId={selectedBatchRunId}
            pages={batchPages}
            selectedPage={selectedBatchPage}
            ocrEngines={ocrEngines}
            message={batchMessage}
            onRunChange={(runId) => {
              setSelectedBatchRunId(runId);
              setSelectedBatchPage(null);
            }}
            onCreateRun={createBatchRun}
            onLoadPages={loadBatchPages}
            onLoadPage={loadBatchPage}
            onSavePage={saveBatchPage}
            onSyncOcr={syncBatchPageOcr}
            onPromote={promoteBatchRun}
            onDeleteRun={deleteBatchRun}
            onJumpToReadingDesk={jumpToReadingPage}
            sources={readingSources}
            onRefresh={refreshAll}
          />
        )}
      </section>

      {/* Spreadsheet Hand-Editing Modals */}
      {editingEntity && (
        <div className="customModalOverlay">
          <div className="customModal">
            <h3 className="customModalTitle">Edit Entity</h3>
            <div className="customModalBody">
              <label className="deskField">
                <span>Canonical Name</span>
                <input 
                  type="text" 
                  value={editingEntity.canonical_name || ""} 
                  onChange={(e) => setEditingEntity({ ...editingEntity, canonical_name: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Name (Original)</span>
                <input 
                  type="text" 
                  value={editingEntity.name_original || ""} 
                  onChange={(e) => setEditingEntity({ ...editingEntity, name_original: e.target.value })}
                />
              </label>
              <CategorySelector
                label="Type"
                value={editingEntity.entity_type || "person"}
                onChange={(val) => setEditingEntity({ ...editingEntity, entity_type: val })}
                types={entityTypes}
                setTypes={setEntityTypes}
                isEntity={true}
              />
              <label className="deskField">
                <span>Aliases (Comma separated)</span>
                <input 
                  type="text" 
                  value={editingEntity.aliasesString || ""} 
                  onChange={(e) => setEditingEntity({ ...editingEntity, aliasesString: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Notes</span>
                <textarea 
                  value={editingEntity.notes || ""} 
                  onChange={(e) => setEditingEntity({ ...editingEntity, notes: e.target.value })}
                />
              </label>
            </div>
            <div className="customModalActions">
              <button className="quietButton light" onClick={() => setEditingEntity(null)}>Cancel</button>
              <button 
                className="primaryButton" 
                onClick={() => handleUpdateEntity({
                  ...editingEntity,
                  aliases: editingEntity.aliasesString.split(",").map(a => a.trim()).filter(Boolean)
                })}
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {editingRelationship && (
        <div className="customModalOverlay">
          <div className="customModal">
            <h3 className="customModalTitle">Edit Relationship Claim</h3>
            <div className="customModalBody">
              <label className="deskField">
                <span>Subject Name</span>
                <input 
                  type="text" 
                  value={editingRelationship.subject_name || ""} 
                  onChange={(e) => setEditingRelationship({ ...editingRelationship, subject_name: e.target.value })}
                />
              </label>
              <CategorySelector
                label="Relation Type"
                value={editingRelationship.relation_type || "spouse"}
                onChange={(val) => setEditingRelationship({ ...editingRelationship, relation_type: val })}
                types={relationTypes}
                setTypes={setRelationTypes}
                isEntity={false}
              />
              <label className="deskField">
                <span>Object Name</span>
                <input 
                  type="text" 
                  value={editingRelationship.object_name || ""} 
                  onChange={(e) => setEditingRelationship({ ...editingRelationship, object_name: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Confidence</span>
                <select 
                  value={editingRelationship.confidence || "medium"} 
                  onChange={(e) => setEditingRelationship({ ...editingRelationship, confidence: e.target.value })}
                >
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </label>
              <label className="deskField">
                <span>Note</span>
                <textarea 
                  value={editingRelationship.note || ""} 
                  onChange={(e) => setEditingRelationship({ ...editingRelationship, note: e.target.value })}
                />
              </label>
            </div>
            <div className="customModalActions">
              <button className="quietButton light" onClick={() => setEditingRelationship(null)}>Cancel</button>
              <button 
                className="primaryButton" 
                onClick={() => handleUpdateRelationship({
                  source_id: editingRelationship.source_id,
                  relationship_id: editingRelationship.relationship_id,
                  relation_type: editingRelationship.relation_type,
                  confidence: editingRelationship.confidence,
                  note: editingRelationship.note,
                  page: editingRelationship.page,
                  evidence_id: editingRelationship.evidence_id,
                  quote: editingRelationship.quote,
                  subject: {
                    entity_id: editingRelationship.subject_entity_id,
                    name: editingRelationship.subject_name,
                    entity_type: editingRelationship.subject_type || "person"
                  },
                  object: {
                    entity_id: editingRelationship.object_entity_id,
                    name: editingRelationship.object_name,
                    entity_type: editingRelationship.object_type || "person"
                  }
                })}
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {editingAttitude && (
        <div className="customModalOverlay">
          <div className="customModal">
            <h3 className="customModalTitle">Edit Attitude Claim</h3>
            <div className="customModalBody">
              <label className="deskField">
                <span>Speaker Name</span>
                <input 
                  type="text" 
                  value={editingAttitude.speaker_name || ""} 
                  onChange={(e) => setEditingAttitude({ ...editingAttitude, speaker_name: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Attitude Type</span>
                <input 
                  type="text" 
                  value={editingAttitude.attitude_type || ""} 
                  onChange={(e) => setEditingAttitude({ ...editingAttitude, attitude_type: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Polarity</span>
                <select 
                  value={editingAttitude.polarity || "positive"} 
                  onChange={(e) => setEditingAttitude({ ...editingAttitude, polarity: e.target.value })}
                >
                  <option value="positive">Positive</option>
                  <option value="negative">Negative</option>
                  <option value="neutral">Neutral</option>
                </select>
              </label>
              <label className="deskField">
                <span>Target Name</span>
                <input 
                  type="text" 
                  value={editingAttitude.target_name || ""} 
                  onChange={(e) => setEditingAttitude({ ...editingAttitude, target_name: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Confidence</span>
                <select 
                  value={editingAttitude.confidence || "medium"} 
                  onChange={(e) => setEditingAttitude({ ...editingAttitude, confidence: e.target.value })}
                >
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </label>
              <label className="deskField">
                <span>Note</span>
                <textarea 
                  value={editingAttitude.note || ""} 
                  onChange={(e) => setEditingAttitude({ ...editingAttitude, note: e.target.value })}
                />
              </label>
            </div>
            <div className="customModalActions">
              <button className="quietButton light" onClick={() => setEditingAttitude(null)}>Cancel</button>
              <button 
                className="primaryButton" 
                onClick={() => handleUpdateAttitude({
                  source_id: editingAttitude.source_id,
                  attitude_id: editingAttitude.attitude_id,
                  attitude_type: editingAttitude.attitude_type,
                  polarity: editingAttitude.polarity,
                  confidence: editingAttitude.confidence,
                  note: editingAttitude.note,
                  page: editingAttitude.page,
                  evidence_id: editingAttitude.evidence_id,
                  quote: editingAttitude.quote,
                  speaker: {
                    entity_id: editingAttitude.speaker_entity_id,
                    name: editingAttitude.speaker_name,
                    entity_type: editingAttitude.speaker_type || "person"
                  },
                  target: {
                    entity_id: editingAttitude.target_entity_id,
                    name: editingAttitude.target_name,
                    entity_type: editingAttitude.target_type || "person"
                  }
                })}
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {evidence && <EvidenceDrawer evidence={evidence} onClose={() => setEvidence(null)} onJumpToReadingDesk={jumpToReadingPage} />}
      <MergeEntitiesModal 
        isOpen={mergeModalOpen} 
        onClose={() => setMergeModalOpen(false)} 
        entities={entities} 
        onMerge={handleMergeEntities} 
        initialTargetId={mergeInitialTargetId} 
      />
      {showNewProjectModal && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(0, 0, 0, 0.4)",
          backdropFilter: "blur(4px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 9999,
        }}>
          <div style={{
            background: "var(--bg-surface, #fff)",
            padding: 24,
            borderRadius: 12,
            border: "1px solid var(--border-color)",
            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.15)",
            width: 400,
            maxWidth: "90%",
          }}>
            <h3 style={{ marginTop: 0, marginBottom: 16, fontSize: 18, fontWeight: 600 }}>Create New Project</h3>
            <input
              type="text"
              placeholder="Project Name (e.g. Meiji Restoration)"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: 6,
                border: "1px solid var(--border-color)",
                marginBottom: 16,
                fontSize: 14,
                boxSizing: "border-box",
                background: "var(--bg-surface-elevated, #fff)",
                color: "var(--text-primary)",
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreateProject();
              }}
              autoFocus
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
              <button
                className="quietButton"
                onClick={() => {
                  setShowNewProjectModal(false);
                  setNewProjectName("");
                }}
                style={{ padding: "8px 16px", borderRadius: 6 }}
              >
                Cancel
              </button>
              <button
                className="primaryButton"
                onClick={handleCreateProject}
                disabled={!newProjectName.trim()}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  background: "var(--color-primary, #1e40af)",
                  color: "#fff",
                  border: "none",
                  cursor: newProjectName.trim() ? "pointer" : "not-allowed",
                  opacity: newProjectName.trim() ? 1 : 0.6,
                }}
              >
                Create
              </button>
            </div>
            <div style={{ marginTop: 16, borderTop: "1px solid var(--border-color)", paddingTop: 16 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", display: "block", marginBottom: 8 }}>
                Or import from a sources JSON file:
              </span>
              <input
                type="file"
                accept=".json"
                onChange={async (e) => {
                  const file = e.target.files[0];
                  if (!file) return;
                  const defaultName = file.name.replace(/\.[^/.]+$/, "");
                  const customName = prompt("Enter project name:", defaultName);
                  if (!customName || !customName.trim()) return;
                  try {
                    setLoading(true);
                    const reader = new FileReader();
                    reader.onload = async (event) => {
                      try {
                        const resultText = typeof event.target?.result === "string" ? event.target.result : "";
                        const jsonContent = JSON.parse(resultText);
                        const res = await fetchJson(`/api/v1/projects/import?name=${encodeURIComponent(customName)}`, {
                          method: "POST",
                          body: JSON.stringify(jsonContent),
                        });
                        setShowNewProjectModal(false);
                        const data = await fetchJson("/api/v1/projects");
                        setProjects(data.projects);
                        await switchProject(res.project_id);
                      } catch (err) {
                        alert(`Import failed: ${err.message}`);
                      } finally {
                        setLoading(false);
                      }
                    };
                    reader.readAsText(file);
                  } catch (err) {
                    alert(`Failed to read file: ${err.message}`);
                    setLoading(false);
                  }
                }}
                style={{
                  fontSize: 13,
                  color: "var(--text-primary)",
                  width: "100%",
                }}
              />
            </div>
          </div>
        </div>
      )}

      {showProjectNoteModal && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(0, 0, 0, 0.4)",
          backdropFilter: "blur(4px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 9999,
        }}>
          <div style={{
            background: "var(--bg-surface, #fff)",
            padding: 24,
            borderRadius: 12,
            border: "1px solid var(--border-color)",
            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.15)",
            width: 600,
            maxWidth: "90%",
          }}>
            <h3 style={{ marginTop: 0, marginBottom: 16, fontSize: 18, fontWeight: 600 }}>Project Research Notes & Context</h3>
            <div style={{ marginBottom: 12, fontSize: "0.85rem", color: "var(--text-secondary)" }}>
              Define the overarching context and research goals of the active project. These notes will be embedded as YAML frontmatter in Markdown exports.
            </div>
            <textarea
              value={projectNoteText}
              onChange={(e) => setProjectNoteText(e.target.value)}
              placeholder="Enter project description, historical context, sources list, translation guides, or notes..."
              style={{
                width: "100%",
                height: 300,
                padding: "8px 12px",
                borderRadius: 6,
                border: "1px solid var(--border-color)",
                marginBottom: 16,
                fontSize: 14,
                boxSizing: "border-box",
                background: "var(--bg-surface-elevated, #fff)",
                color: "var(--text-primary)",
                resize: "vertical",
                fontFamily: "inherit"
              }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
              <button
                className="quietButton"
                onClick={() => setShowProjectNoteModal(false)}
                style={{ padding: "8px 16px", borderRadius: 6 }}
              >
                Cancel
              </button>
              <button
                className="primaryButton"
                onClick={() => saveProjectNote(activeProject, projectNoteText)}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  background: "var(--color-primary, #1e40af)",
                  color: "#fff",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                Save Notes
              </button>
            </div>
          </div>
        </div>
      )}

      {showSourceMetadataModal && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(0, 0, 0, 0.4)",
          backdropFilter: "blur(4px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 9999,
        }}>
          <div style={{
            background: "var(--bg-surface, #fff)",
            padding: 24,
            borderRadius: 12,
            border: "1px solid var(--border-color)",
            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.15)",
            width: 550,
            maxWidth: "90%",
          }}>
            <h3 style={{ marginTop: 0, marginBottom: 16, fontSize: 18, fontWeight: 600 }}>Edit Source Metadata</h3>
            
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>Title</span>
                <input
                  type="text"
                  value={metaTitle}
                  onChange={(e) => setMetaTitle(e.target.value)}
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--border-color)",
                    background: "var(--bg-surface-elevated, #fff)",
                    color: "var(--text-primary)",
                    fontSize: 14
                  }}
                />
              </label>

              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>Collection / Volume</span>
                <input
                  type="text"
                  value={metaCollection}
                  onChange={(e) => setMetaCollection(e.target.value)}
                  placeholder="e.g. Imperial Shōgunate Biographies, Vol. 4"
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--border-color)",
                    background: "var(--bg-surface-elevated, #fff)",
                    color: "var(--text-primary)",
                    fontSize: 14
                  }}
                />
              </label>

              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>Bibliographic Citation</span>
                <input
                  type="text"
                  value={metaCitation}
                  onChange={(e) => setMetaCitation(e.target.value)}
                  placeholder="e.g. Tokyo: National Diet Library, 1923"
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--border-color)",
                    background: "var(--bg-surface-elevated, #fff)",
                    color: "var(--text-primary)",
                    fontSize: 14
                  }}
                />
              </label>

              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>Source-level Research Notes</span>
                <textarea
                  value={metaNotes}
                  onChange={(e) => setMetaNotes(e.target.value)}
                  placeholder="Context of this specific source document, archival details, provenance history..."
                  style={{
                    height: 120,
                    padding: "8px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--border-color)",
                    background: "var(--bg-surface-elevated, #fff)",
                    color: "var(--text-primary)",
                    fontSize: 14,
                    resize: "vertical",
                    fontFamily: "inherit"
                  }}
                />
              </label>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
              <button
                className="quietButton"
                onClick={() => setShowSourceMetadataModal(false)}
                style={{ padding: "8px 16px", borderRadius: 6 }}
              >
                Cancel
              </button>
              <button
                className="primaryButton"
                onClick={handleSaveSourceMetadata}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  background: "var(--color-primary, #1e40af)",
                  color: "#fff",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

interface EngineOption {
  name: string;
  label: string;
  type: "select" | "boolean";
  default: any;
  choices?: { value: string; label: string }[];
}

interface OcrEngine {
  engine_id: string;
  label: string;
  options_schema?: EngineOption[];
}

interface DynamicEngineSettingsProps {
  engineId: string;
  engines: OcrEngine[];
  settings: Record<string, any>;
  onChange: (key: string, value: any) => void;
  layout?: "vertical" | "horizontal";
}

function DynamicEngineSettings({
  engineId,
  engines,
  settings,
  onChange,
  layout = "horizontal",
}: DynamicEngineSettingsProps) {
  const engine = (engines || []).find((e) => e.engine_id === engineId);
  if (!engine || !engine.options_schema || engine.options_schema.length === 0) {
    return null;
  }

  const containerStyle: React.CSSProperties =
    layout === "vertical"
      ? {
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          padding: "10px",
          backgroundColor: "var(--bg-light, #f7f5f0)",
          border: "1px solid var(--border-color, #e1dacd)",
          borderRadius: "4px",
          fontSize: "12px",
          width: "100%",
          boxSizing: "border-box",
        }
      : {
          display: "flex",
          alignItems: "center",
          gap: "12px",
          padding: "8px 16px",
          backgroundColor: "var(--bg-light, #f7f5f0)",
          borderBottom: "1px solid var(--border-color, #e1dacd)",
          fontSize: "12px",
          width: "100%",
          boxSizing: "border-box",
        };

  return (
    <div style={containerStyle}>
      <div style={{ fontWeight: "bold" }}>
        {engine.label} Options{layout === "horizontal" ? ":" : ""}
      </div>
      <div
        style={{
          display: "flex",
          gap: "10px",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {engine.options_schema.map((opt) => {
          const val = settings[opt.name] !== undefined ? settings[opt.name] : opt.default;
          if (opt.type === "select") {
            return (
              <label
                key={opt.name}
                style={{
                  display: "flex",
                  flexDirection: layout === "vertical" ? "column" : "row",
                  alignItems: layout === "vertical" ? "flex-start" : "center",
                  gap: "2px",
                }}
              >
                <span style={layout === "vertical" ? { fontSize: "11px", color: "#666" } : undefined}>
                  {opt.label}
                </span>
                <select
                  value={val}
                  onChange={(e) => onChange(opt.name, e.target.value)}
                  style={{
                    padding: "2px",
                    borderRadius: "3px",
                    border: "1px solid var(--border-color, #e1dacd)",
                  }}
                >
                  {opt.choices?.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>
            );
          } else if (opt.type === "boolean") {
            return (
              <label
                key={opt.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                  cursor: "pointer",
                  height: layout === "vertical" ? "24px" : "auto",
                  alignSelf: layout === "vertical" ? "flex-end" : "auto",
                }}
              >
                <input
                  type="checkbox"
                  checked={!!val}
                  onChange={(e) => onChange(opt.name, e.target.checked)}
                />
                <span>{opt.label}</span>
              </label>
            );
          }
          return null;
        })}
      </div>
    </div>
  );
}

function BatchReview({
  runs,
  selectedRunId,
  pages,
  selectedPage,
  ocrEngines,
  message,
  onRunChange,
  onCreateRun,
  onLoadPages,
  onLoadPage,
  onSavePage,
  onSyncOcr,
  onPromote,
  onDeleteRun,
  onJumpToReadingDesk,
  sources,
  onRefresh,
}) {
  const [filters, setFilters] = useState({ source_id: "", page: "", candidate_type: "", status: "", ocr_status: "" });
  const [draftPage, setDraftPage] = useState(null);
  const [showRejected, setShowRejected] = useState(false);

  // Redesign: Local state for Left Panel configuration placeholders
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [selectedOcrMethod, setSelectedOcrMethod] = useState("ndlocr_lite");
  const [ocrSettings, setOcrSettings] = useState<Record<string, any>>({});
  const [selectedNlpMethod, setSelectedNlpMethod] = useState("gliner");
  const [glinerLabels, setGlinerLabels] = useState("person, place, organization, group, event, document");
  const [glinerRelations, setGlinerRelations] = useState("spouse, parent, child, colleague, employer, opponent, ally");
  const [slmPrompt, setSlmPrompt] = useState("Extract all entities, relationships, and evidence quotes from this text in Japanese.");
  const [llmPrompt, setLlmPrompt] = useState("Identify all key actors, organizations, relationships, and supporting evidence quotes.");
  const [runProgress, setRunProgress] = useState("");

  // Accordion expanded state for quote cards
  const [expandedQuotes, setExpandedQuotes] = useState({});

  // Keep logs of the active run status updates
  const [logs, setLogs] = useState<string[]>([]);
  const lastStatus = useRef("");

  const activeRun = runs.find((run) =>
    run.status === "processing" ||
    (run.status && (
      run.status.startsWith("Installing") ||
      run.status.startsWith("Loading") ||
      run.status.startsWith("Running") ||
      run.status.startsWith("Text") ||
      run.status.includes("/")
    ))
  );

  useEffect(() => {
    // Clear logs when active run changes
    setLogs([]);
    lastStatus.current = "";
  }, [activeRun?.run_id]);

  useEffect(() => {
    if (activeRun?.status) {
      const status = activeRun.status;
      if (status !== lastStatus.current) {
        setLogs((prev) => {
          if (prev.includes(status)) return prev;
          return [...prev, status];
        });
        lastStatus.current = status;
      }
    }
  }, [activeRun?.status]);

  useEffect(() => {
    setDraftPage(selectedPage ? JSON.parse(JSON.stringify(selectedPage)) : null);
  }, [selectedPage]);

  const selectedRun = runs.find((run) => run.run_id === selectedRunId);

  function updateFilter(name, value) {
    const next = { ...filters, [name]: value };
    setFilters(next);
    onLoadPages(selectedRunId, next);
  }

  function pageWithCandidateUpdate(page, group, candidateId, updates) {
    if (!page) return null;
    return {
      ...page,
      [group]: page[group].map((candidate) => (
        candidate.candidate_id === candidateId ? { ...candidate, ...updates } : candidate
      )),
    };
  }

  function updateCandidate(group, candidateId, updates) {
    setDraftPage((current) => pageWithCandidateUpdate(current, group, candidateId, updates));
  }

  async function setCandidateStatus(group, candidateId, status) {
    const next = pageWithCandidateUpdate(draftPage, group, candidateId, {
      review_status: status,
      promotion_skip_reason: "",
      promotion_message: "",
    });
    if (!next) return;
    setDraftPage(next);
    await onSavePage(next, { quiet: true });
    if (status === "approved") {
      await onPromote(next.run_id, next.source_id, next.page);
    }
  }

  const toggleQuoteExpanded = (quoteId) => {
    setExpandedQuotes((prev) => ({ ...prev, [quoteId]: !prev[quoteId] }));
  };

  function structuredTextUpdate(candidate, value) {
    const kind = candidate.kind || candidate.candidate_type;
    const updates: FlexibleRecord = { label: value };
    if (kind === "entity" || kind === "place") {
      updates.entity_name = value;
      updates.entity = { ...(candidate.entity || {}), name: value };
    } else if (kind === "keyword") {
      updates.keyword = value;
    } else if (kind === "claim") {
      updates.claim = { ...(candidate.claim || {}), text: value };
    } else if (kind === "note") {
      updates.note = value;
    }
    return updates;
  }

  function relationshipEditor(candidate) {
    const relationship = candidate.relationship || {};
    const subject = relationship.subject || {};
    const objectRecord = relationship.object || {};
    return (
      <div className="candidateMiniGrid">
        <label>
          <span>Subject</span>
          <input
            value={subject.name || ""}
            onChange={(event) => updateCandidate("structured_candidates", candidate.candidate_id, {
              relationship: { ...relationship, subject: { ...subject, name: event.target.value } },
            })}
          />
        </label>
        <label>
          <span>Relation</span>
          <input
            value={relationship.relation_type || ""}
            onChange={(event) => updateCandidate("structured_candidates", candidate.candidate_id, {
              relationship: { ...relationship, relation_type: event.target.value },
            })}
            placeholder="e.g. criticism, affiliation"
          />
        </label>
        <label>
          <span>Object</span>
          <input
            value={objectRecord.name || ""}
            onChange={(event) => updateCandidate("structured_candidates", candidate.candidate_id, {
              relationship: { ...relationship, object: { ...objectRecord, name: event.target.value } },
            })}
          />
        </label>
      </div>
    );
  }

  function attitudeEditor(candidate) {
    const attitude = candidate.attitude || {};
    const speaker = attitude.speaker || {};
    const target = attitude.target || {};
    return (
      <div className="candidateMiniGrid">
        <label>
          <span>Speaker</span>
          <input
            value={speaker.name || ""}
            onChange={(event) => updateCandidate("structured_candidates", candidate.candidate_id, {
              attitude: { ...attitude, speaker: { ...speaker, name: event.target.value } },
            })}
          />
        </label>
        <label>
          <span>Attitude</span>
          <input
            value={attitude.attitude_type || ""}
            onChange={(event) => updateCandidate("structured_candidates", candidate.candidate_id, {
              attitude: { ...attitude, attitude_type: event.target.value },
            })}
            placeholder="e.g. criticism, support"
          />
        </label>
        <label>
          <span>Polarity</span>
          <select
            value={attitude.polarity || ""}
            onChange={(event) => updateCandidate("structured_candidates", candidate.candidate_id, {
              attitude: { ...attitude, polarity: event.target.value },
            })}
          >
            <option value="">Choose</option>
            <option value="positive">positive</option>
            <option value="negative">negative</option>
            <option value="neutral">neutral</option>
            <option value="mixed">mixed</option>
          </select>
        </label>
        <label>
          <span>Target</span>
          <input
            value={target.name || ""}
            onChange={(event) => updateCandidate("structured_candidates", candidate.candidate_id, {
              attitude: { ...attitude, target: { ...target, name: event.target.value } },
            })}
          />
        </label>
      </div>
    );
  }

  function visibleCandidate(candidate) {
    return showRejected || candidate.review_status !== "rejected";
  }

  function candidateActions(group, candidate) {
    const status = candidate.review_status || "candidate";
    if (status === "rejected" || status === "promoted") {
      return (
        <button className="quietButton light" type="button" onClick={() => setCandidateStatus(group, candidate.candidate_id, "candidate")}>
          Undo
        </button>
      );
    }
    return (
      <>
        <button
          className={status === "approved" ? "primaryButton" : "quietButton light"}
          type="button"
          onClick={() => setCandidateStatus(group, candidate.candidate_id, "approved")}
        >
          Approve
        </button>
        <button className="quietButton light dangerButton" type="button" onClick={() => setCandidateStatus(group, candidate.candidate_id, "rejected")}>
          Reject
        </button>
      </>
    );
  }

  const quoteCandidates = (draftPage?.quote_candidates || []).filter(visibleCandidate);
  const structuredCandidates = (draftPage?.structured_candidates || []).filter(visibleCandidate);
  const displayedOcrLayer = draftPage?.displayed_ocr_layer || draftPage?.ocr_layer || "none";
  const latestOcrLayer = draftPage?.latest_available_ocr_layer || "none";

  return (
    <div className="batchReviewGrid">
      <section className="panel batchQueuePanel">
        <PanelTitle icon={<Database size={18} />} title="Batch Processing Control" />
        <p className="muted" style={{ marginBottom: "14px" }}>
          Configure batch extraction for a whole source document (PDF/ZIP).
        </p>

        <div style={{
          display: "flex",
          flexDirection: "column",
          gap: "14px",
          marginBottom: "24px",
          padding: "16px",
          background: "var(--bg-surface-elevated, #fcfbf9)",
          borderRadius: "8px",
          border: "1px solid var(--border-color, #e1dacd)"
        }}>
          <label className="deskField" style={{ margin: 0 }}>
            <span>Target Source</span>
            <select value={selectedSourceId} onChange={(e) => setSelectedSourceId(e.target.value)}>
              <option value="">Select a source...</option>
              {sources && sources.map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.title_original || s.title || s.source_id}
                </option>
              ))}
            </select>
          </label>

          <label className="deskField" style={{ margin: 0 }}>
            <span>OCR Method</span>
            <select value={selectedOcrMethod} onChange={(e) => setSelectedOcrMethod(e.target.value)}>
              <option value="none">None (Skip OCR / Use existing OCR)</option>
              {(ocrEngines || []).map((eng) => {
                const engineId = typeof eng === "string" ? eng : (eng?.engine_id || "");
                const label = typeof eng === "string" ? eng : (eng?.label || engineId);
                return (
                  <option key={engineId} value={engineId}>
                    {label}
                  </option>
                );
              })}
            </select>
          </label>

          <DynamicEngineSettings
            engineId={selectedOcrMethod}
            engines={ocrEngines}
            settings={ocrSettings}
            onChange={(name, val) => setOcrSettings((prev) => ({ ...prev, [name]: val }))}
            layout="vertical"
          />

          <button
            className="primaryButton"
            type="button"
            onClick={async () => {
              try {
                setRunProgress("Starting batch OCR background task...");
                const activeEngine = ocrEngines.find((e) => e.engine_id === selectedOcrMethod);
                const engineSettings: Record<string, any> = {};
                if (activeEngine?.options_schema) {
                  activeEngine.options_schema.forEach((opt) => {
                    const val = ocrSettings[opt.name] !== undefined ? ocrSettings[opt.name] : opt.default;
                    engineSettings[opt.name] = val;
                  });
                }
                const res = await fetchJson("/api/batch/extract", {
                  method: "POST",
                  body: JSON.stringify({
                    source_id: selectedSourceId,
                    ocr_engine: selectedOcrMethod,
                    nlp_method: "none",
                    ...engineSettings,
                  }),
                });
                setRunProgress(`Task started: ${res.message || res.run_id}`);
                if (res.run_id) {
                  onRunChange(res.run_id);
                  onLoadPages(res.run_id);
                  if (onRefresh) {
                    await onRefresh();
                  }
                }
                setTimeout(() => setRunProgress(""), 5000);
              } catch (err) {
                setRunProgress(`Error: ${err.message}`);
                setTimeout(() => setRunProgress(""), 6000);
              }
            }}
            disabled={!selectedSourceId || selectedOcrMethod === "none"}
            style={{ width: "100%", justifyContent: "center" }}
          >
            {selectedOcrMethod === "none" ? "Select OCR Method" : "Run Batch OCR"}
          </button>

          {runProgress && (
            <div className="statusBadge info" style={{ display: "block", textAlign: "center", padding: "6px", width: "100%", boxSizing: "border-box" }}>
              {runProgress}
            </div>
          )}

        </div>

        <div style={{ borderTop: "1px solid var(--border-color, #e1dacd)", paddingTop: "16px" }}>
          <PanelTitle icon={<Database size={16} />} title="Batch Review Queue" />
          <p className="muted">Select a provisional run and page below to review candidate extractions.</p>
          
          <div className="readerActions" style={{ margin: "12px 0" }}>
            <button className="primaryButton" type="button" onClick={() => onCreateRun()}>
              Create sample run
            </button>
            <button className="quietButton light" type="button" onClick={() => onPromote(selectedRunId)}>
              Save approved items
            </button>
            <button className="quietButton light dangerButton" type="button" onClick={() => onDeleteRun(selectedRunId)} disabled={!selectedRunId}>
              Delete run
            </button>
          </div>
          {message && <div className={isPositiveMessage(message) ? "successBanner" : "errorBanner inline"}>{message}</div>}

          <label className="deskField">
            <span>Select Batch Run</span>
            <select value={selectedRunId} onChange={(event) => onRunChange(event.target.value)}>
              <option value="">Choose a batch run</option>
              {runs.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {batchRunLabel(run)}
                </option>
              ))}
            </select>
          </label>

          {selectedRun && (
            <div style={{
              padding: "14px",
              background: "var(--bg-surface-elevated, #fcfbf9)",
              border: "1px solid var(--border-color, #e1dacd)",
              borderRadius: "8px",
              marginBottom: "16px",
              marginTop: "8px",
              boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
              transition: "all 0.2s ease"
            }}>
              <div style={{ 
                display: "flex", 
                justifyContent: "space-between", 
                alignItems: "center",
                fontSize: "12px", 
                fontWeight: 600, 
                color: "var(--text-primary)"
              }}>
                <span>Run Status</span>
                <span>{getStatusPercent(selectedRun.status)}%</span>
              </div>
              <div 
                className={selectedRun.status?.toLowerCase().includes("failed") || selectedRun.status?.toLowerCase().includes("error") ? "statusBadge error" : "muted"}
                style={{ 
                  fontSize: "11px", 
                  marginTop: "6px", 
                  fontStyle: "italic",
                  lineHeight: "1.4",
                  wordBreak: "break-word",
                  display: "inline-block",
                  padding: selectedRun.status?.toLowerCase().includes("failed") || selectedRun.status?.toLowerCase().includes("error") ? "4px 8px" : "0",
                  borderRadius: "4px"
                }}
              >
                {selectedRun.status}
              </div>
              <div className="progressBarContainer" style={{ background: "var(--border-color-light, #f5f5f5)", borderRadius: 4, height: 6, width: "100%", overflow: "hidden", marginTop: 10 }}>
                <div 
                  className="progressBarFill" 
                  style={{ 
                    background: selectedRun.status?.toLowerCase().includes("failed") || selectedRun.status?.toLowerCase().includes("error") ? "#d93838" : "var(--accent-primary, #7d3d2f)", 
                    width: `${getStatusPercent(selectedRun.status)}%`, 
                    height: "100%", 
                    transition: "width 0.3s ease" 
                  }} 
                />
              </div>
            </div>
          )}

          <div className="inlineFields" style={{ marginTop: "12px" }}>
            <input value={filters.source_id} onChange={(event) => updateFilter("source_id", event.target.value)} placeholder="Source ID" />
            <input value={filters.page} onChange={(event) => updateFilter("page", event.target.value.replace(/\D/g, ""))} placeholder="Page" />
          </div>

          <div className="batchPageList" style={{ marginTop: "12px" }}>
            {pages.map((page) => (
              <button
                className="rowButton"
                type="button"
                key={`${page.source_id}_${page.page}`}
                onClick={() => onLoadPage(selectedRunId, page.source_id, page.page)}
              >
                <strong>{page.title_original || page.title} p.{page.page}</strong>
                <span>
                  {page.ocr_status} · {page.quote_candidate_count} quotes · {page.structured_candidate_count} structured
                </span>
              </button>
            ))}
            {pages.length === 0 && (
              <p className="muted">No pages found in this run.</p>
            )}
          </div>
        </div>
      </section>

      <section className="panel batchPagePanel">
        {activeRun ? (
          <>
            <PanelTitle icon={<Database size={18} />} title="Active Batch Process Status" />
            <div style={{
              display: "flex",
              flexDirection: "column",
              gap: "14px",
              padding: "16px",
              background: "var(--bg-surface-elevated, #fcfbf9)",
              borderRadius: "8px",
              border: "1px solid var(--border-color, #e1dacd)",
              marginTop: "12px"
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>
                <span>Run Status ({activeRun.run_id})</span>
                <span>{getStatusPercent(activeRun.status)}%</span>
              </div>
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", fontStyle: "italic", lineHeight: "1.4", wordBreak: "break-word" }}>
                {activeRun.status}
              </div>
              <div className="progressBarContainer" style={{ background: "var(--border-color-light, #f5f5f5)", borderRadius: 4, height: 8, width: "100%", overflow: "hidden" }}>
                <div className="progressBarFill" style={{ background: "var(--accent-primary, #7d3d2f)", width: `${getStatusPercent(activeRun.status)}%`, height: "100%", transition: "width 0.3s ease" }} />
              </div>
              
              <h4 style={{ marginTop: "14px", marginBottom: "4px", color: "var(--text-primary)", fontSize: "13px" }}>Terminal Progress Messages</h4>
              <div style={{
                background: "#172326",
                color: "#cbd8d5",
                fontFamily: "monospace",
                padding: "12px",
                borderRadius: "6px",
                height: "220px",
                overflowY: "auto",
                fontSize: "12px",
                lineHeight: "1.5"
              }}>
                {logs.map((log, i) => (
                  <div key={i} style={{ marginBottom: "4px" }}>
                    &gt; {log}
                  </div>
                ))}
                {logs.length === 0 && (
                  <div style={{ color: "#718083", fontStyle: "italic" }}>Waiting for progress messages...</div>
                )}
              </div>
              
              <button
                className="quietButton light dangerButton"
                type="button"
                onClick={async () => {
                  try {
                    await fetchJson(`/api/v1/batches/biographies/runs/${activeRun.run_id}/stop`, {
                      method: "POST"
                    });
                    if (onRefresh) {
                      await onRefresh();
                    }
                  } catch (err) {
                    console.error("Stopping run failed:", err);
                  }
                }}
                style={{ marginTop: "8px", width: "100%", justifyContent: "center" }}
              >
                Stop Batch Process
              </button>
            </div>
          </>
        ) : !draftPage ? (
          <>
            <PanelTitle icon={<NotebookPen size={18} />} title="Batch Page Review" />
            <p className="muted">Select a page from the queue on the left.</p>
          </>
        ) : (
          <>
            <PanelTitle icon={<NotebookPen size={18} />} title="Batch Page Review" />
            <div className="statusBadgeRow">
              <span className="statusBadge warning">Batch candidate</span>
              <span className="statusBadge success">Promoted only after approval</span>
              <span className="statusBadge info">Showing {displayedOcrLayer} OCR</span>
              {draftPage.worker_ai_status && <span className="statusBadge info">Worker: {draftPage.worker_ai_status}</span>}
              {draftPage.ocr_is_stale && <span className="statusBadge warning">Corrected OCR available</span>}
              {draftPage.ocr_review_status === "edited" && <span className="statusBadge warning">Batch OCR edited; not auto-overwritten</span>}
            </div>
            <h1>{draftPage.title_original || draftPage.title} · page {draftPage.page}</h1>
            <dl className="compactMeta tight" style={{ marginBottom: "20px" }}>
              <div><dt>Displayed OCR</dt><dd>{displayedOcrLayer}</dd></div>
              <div><dt>Displayed path</dt><dd>{draftPage.displayed_ocr_page_json || draftPage.ocr_page_json || "none"}</dd></div>
              <div><dt>Latest available</dt><dd>{latestOcrLayer}</dd></div>
              <div><dt>Latest path</dt><dd>{draftPage.latest_available_ocr_page_json || "none"}</dd></div>
              <div><dt>Network review</dt><dd>{draftPage.network_review_status || "pending"}</dd></div>
              <div><dt>Analysis</dt><dd>{draftPage.analysis_engine || "local_fallback"}</dd></div>
              <div><dt>Worker</dt><dd>{draftPage.worker_ai_provider || "none"} {draftPage.worker_ai_model || ""}</dd></div>
            </dl>
            {draftPage.worker_ai_message && <p className="muted">{draftPage.worker_ai_message}</p>}
            {draftPage.ocr_sync_message && <p className="muted">{draftPage.ocr_sync_message}</p>}
            
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px", marginTop: "12px" }}>
              <div className="readerActions" style={{ margin: 0 }}>
                <button className="primaryButton" type="button" onClick={() => onSavePage(draftPage)}>
                  Save page draft
                </button>
                <button className="quietButton light" type="button" onClick={() => onPromote(draftPage.run_id, draftPage.source_id, draftPage.page, draftPage)}>
                  Promote approved page items
                </button>
                <button 
                  className="quietButton light" 
                  type="button" 
                  onClick={() => onSyncOcr(draftPage.run_id, draftPage.source_id, draftPage.page)}
                  style={{
                    border: draftPage.ocr_is_stale ? "1px solid var(--accent-primary, #7d3d2f)" : "",
                    background: draftPage.ocr_is_stale ? "var(--bg-surface-elevated, #fcfbf9)" : "",
                    color: draftPage.ocr_is_stale ? "var(--accent-primary, #7d3d2f)" : ""
                  }}
                  title="Synchronize and parse this page again using the latest proofread OCR from the Reading Desk"
                >
                  {draftPage.ocr_is_stale ? "Sync OCR (Update Available)" : "Sync OCR"}
                </button>
              </div>
              <label className="inlineCheck" style={{ margin: 0 }}>
                <input type="checkbox" checked={showRejected} onChange={(event) => setShowRejected(event.target.checked)} />
                <span>Show rejected candidates</span>
              </label>
            </div>

            <h2>Candidate Evidence Quotes & Entities</h2>
            <p className="muted" style={{ marginBottom: "12px" }}>
              Click any quote card to inspect and approve the entities and relationships extracted from it.
            </p>

            <div className="candidateCardList">
              {quoteCandidates.length === 0 && (
                <p className="muted">No quote candidates for this page yet.</p>
              )}
              {quoteCandidates.map((candidate) => {
                const isExpanded = !!expandedQuotes[candidate.candidate_id];
                // Filter child entities and relations for this quote candidate
                const children = structuredCandidates.filter(
                  (c) => c.quote_candidate_id === candidate.candidate_id || c.evidence_id === `batch_${candidate.candidate_id}`
                );

                return (
                  <div
                    className={`candidateCard quote ${isExpanded ? "expanded" : ""} status-${candidate.review_status || "candidate"}`}
                    key={candidate.candidate_id}
                    style={{ borderLeft: "4px solid #7d3d2f", cursor: "default" }}
                  >
                    <div
                      onClick={() => toggleQuoteExpanded(candidate.candidate_id)}
                      style={{ cursor: "pointer", userSelect: "none" }}
                    >
                      <div className="candidateCardHeader">
                        <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <strong>QUOTE CANDIDATE</strong> 
                          <span className={`statusBadge ${candidate.review_status === "approved" ? "success" : candidate.review_status === "rejected" ? "missing" : "warning"}`} style={{ fontSize: "10px", minHeight: "18px", padding: "0 6px" }}>
                            {candidate.review_status || "pending"}
                          </span>
                        </span>
                        <small>Score {candidate.score ?? "n/a"} (Click to {isExpanded ? "collapse" : "expand"})</small>
                      </div>
                      {candidate.promotion_message && <p className="muted" style={{ margin: "4px 0" }}>{candidate.promotion_message}</p>}
                      {candidate.promotion_skip_reason && <p className="errorText" style={{ margin: "4px 0" }}>{candidate.promotion_skip_reason}</p>}
                      {candidate.matched_terms?.length > 0 && (
                        <div className="statusBadgeRow" style={{ marginTop: "4px" }}>
                          {candidate.matched_terms.slice(0, 6).map((term) => (
                            <span className="statusBadge info" key={`${candidate.candidate_id}_${term.text}`} style={{ fontSize: "10px" }}>
                              {term.text} · {term.entity_type}
                            </span>
                          ))}
                        </div>
                      )}
                      <p className="muted" style={{ margin: "4px 0" }}>
                        {candidate.candidate_reason || "Review suggested passage"}
                      </p>
                    </div>

                    <textarea
                      value={candidate.quote || ""}
                      onChange={(event) => updateCandidate("quote_candidates", candidate.candidate_id, { quote: event.target.value, label: event.target.value, review_status: "edited" })}
                      style={{ width: "100%", minHeight: "60px" }}
                    />

                    <div className="readerActions" style={{ marginTop: "6px" }}>
                      <button
                        className="primaryButton"
                        type="button"
                        onClick={() => setCandidateStatus("quote_candidates", candidate.candidate_id, "approved")}
                      >
                        Approve Quote
                      </button>
                      <button
                        className="quietButton light dangerButton"
                        type="button"
                        onClick={() => setCandidateStatus("quote_candidates", candidate.candidate_id, "rejected")}
                      >
                        Reject Quote
                      </button>
                      {onJumpToReadingDesk && (
                        <button
                          className="quietButton light"
                          type="button"
                          onClick={() => onJumpToReadingDesk(draftPage.source_id, draftPage.page, candidate.quote)}
                        >
                          Locate
                        </button>
                      )}
                    </div>

                    {isExpanded && (
                      <div className="childCandidatesSection" style={{
                        marginTop: "12px",
                        padding: "12px",
                        background: "rgba(0, 0, 0, 0.02)",
                        borderRadius: "6px",
                        borderTop: "1px solid #e1dacd"
                      }}>
                        <h4 style={{ margin: "0 0 10px 0", fontSize: "0.9rem", color: "#7d3d2f" }}>
                          Extracted Entities & Relations ({children.length})
                        </h4>
                        
                        {children.length === 0 && (
                          <p className="muted" style={{ fontSize: "0.85rem", margin: 0 }}>
                            No nested entities or relations found for this quote.
                          </p>
                        )}
                        
                        <div style={{ display: "grid", gap: "10px" }}>
                          {children.map((child) => (
                            <div
                              key={child.candidate_id}
                              style={{
                                padding: "10px",
                                background: child.kind === "relationship" ? "#f7f0ed" : child.kind === "place" ? "#f2f7f5" : "#eef3f1",
                                border: "1px solid #e1dacd",
                                borderRadius: "6px"
                              }}
                            >
                              <div className="candidateCardHeader" style={{ marginBottom: "6px" }}>
                                <span style={{ fontSize: "11px", fontWeight: "bold", textTransform: "uppercase", color: "#647174" }}>
                                  {child.kind || child.candidate_type}
                                </span>
                                <span className={`statusBadge ${child.review_status === "approved" ? "success" : child.review_status === "rejected" ? "missing" : "warning"}`} style={{ fontSize: "9px", minHeight: "16px", padding: "0 4px" }}>
                                  {child.review_status || "pending"}
                                </span>
                              </div>

                              {child.promotion_message && <p className="muted" style={{ margin: "4px 0", fontSize: "0.85rem" }}>{child.promotion_message}</p>}
                              {child.promotion_skip_reason && <p className="errorText" style={{ margin: "4px 0", fontSize: "0.85rem" }}>{child.promotion_skip_reason}</p>}

                              <input
                                type="text"
                                value={child.label || child.keyword || child.note || child.quote || ""}
                                onChange={(event) => updateCandidate("structured_candidates", child.candidate_id, { label: event.target.value, review_status: "edited" })}
                                style={{
                                  width: "100%",
                                  padding: "6px 8px",
                                  fontSize: "0.9rem",
                                  borderRadius: "4px",
                                  border: "1px solid #cfc7ba",
                                  marginBottom: "8px"
                                }}
                              />

                              {child.kind === "relationship" && relationshipEditor(child)}
                              {child.kind === "attitude" && attitudeEditor(child)}

                              <div style={{ display: "flex", gap: "6px" }}>
                                <button
                                  className="primaryButton"
                                  type="button"
                                  style={{ padding: "4px 8px", fontSize: "0.8rem", minHeight: "28px" }}
                                  onClick={() => setCandidateStatus("structured_candidates", child.candidate_id, "approved")}
                                >
                                  Approve
                                </button>
                                <button
                                  className="quietButton light dangerButton"
                                  type="button"
                                  style={{ padding: "4px 8px", fontSize: "0.8rem", minHeight: "28px" }}
                                  onClick={() => setCandidateStatus("structured_candidates", child.candidate_id, "rejected")}
                                >
                                  Reject
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function ReadingDesk({
  sources,
  recentSources,
  source,
  pageData,
  page,
  text,
  ocrEngines,
  onSourceChange,
  onPageChange,
  onTextChange,
  onSaveOcr,
  onSaveEvidence,
  onImportPdf,
  onRenameSource,
  onDeleteSource,
  onReloadPage,
  searchTerm,
  setSearchTerm,
  pageNoteText,
  onPageNoteTextChange,
  onSavePageNote,
}) {
  const imageFrameRef = useRef(null);
  const pageWrapRef = useRef(null);
  const backdropRef = useRef(null);
  const pdfContainerRef = useRef(null);
  const textareaRef = useRef(null);
  const [history, setHistory] = useState([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const isHistoryAction = useRef(false);
  const historyTimeoutRef = useRef(null);

  const [pageRotation, setPageRotation] = useState(0);
  const [pageZoom, setPageZoom] = useState(1);
  const [pageImageVersion, setPageImageVersion] = useState(0);
  const [pageImageError, setPageImageError] = useState("");
  const [pointerMode, setPointerMode] = useState("crop"); // default to crop mode
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [keywordQuery, setKeywordQuery] = useState("");
  const [keywordResults, setKeywordResults] = useState([]);
  const [keywordSearching, setKeywordSearching] = useState(false);
  const [selectedHighlightText, setSelectedHighlightText] = useState("");
  const [clickedHighlight, setClickedHighlight] = useState(null);

  const [showBoundingBoxes, setShowBoundingBoxes] = useState(true);
  const [activeLineIndex, setActiveLineIndex] = useState(-1);
  const [hoveredLineIndex, setHoveredLineIndex] = useState(-1);

  useEffect(() => {
    if (!keywordQuery.trim()) {
      setKeywordResults([]);
      return;
    }
    const delayDebounceFn = setTimeout(async () => {
      setKeywordSearching(true);
      try {
        const results = await fetchJson(`/api/v1/reading/search-ocr?q=${encodeURIComponent(keywordQuery)}`);
        setKeywordResults(results || []);
      } catch (err) {
        console.error(err);
      } finally {
        setKeywordSearching(false);
      }
    }, 400);
    return () => clearTimeout(delayDebounceFn);
  }, [keywordQuery]);
  
  // Search & Replace states
  const [replaceTerm, setReplaceTerm] = useState("");
  const [useRegex, setUseRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);

  // Restored OCR & region states
  const [parsingEngine, setParsingEngine] = useState("ndlocr_lite");
  const [customParsingEngine, setCustomParsingEngine] = useState("");
  const [ocrSettings, setOcrSettings] = useState<Record<string, any>>({});
  const [ocrInsertMode, setOcrInsertMode] = useState("append");
  const [region, setRegion] = useState(null);
  const [regionDrag, setRegionDrag] = useState(null);
  const [regionResult, setRegionResult] = useState(null);
  const [regionOcrResult, setRegionOcrResult] = useState(null);
  const [tableMessage, setTableMessage] = useState("");
  const [panDrag, setPanDrag] = useState(null);

  const handleTextareaScroll = (e) => {
    if (backdropRef.current) {
      backdropRef.current.scrollTop = e.target.scrollTop;
      backdropRef.current.scrollLeft = e.target.scrollLeft;
    }
  };

  useEffect(() => {
    setPageRotation(0);
    setPageZoom(1);
    setPageImageVersion((v) => v + 1);
    setPageImageError("");
    setSelectedHighlightText("");
    setRegion(null);
    setRegionDrag(null);
    setRegionResult(null);
    setRegionOcrResult(null);
    setTableMessage("");
    setActiveLineIndex(-1);
    setHoveredLineIndex(-1);
  }, [pageData?.source?.source_id, page]);

  // Initialize/reset history when text changes due to page change
  useEffect(() => {
    setHistory([text || ""]);
    setHistoryIndex(0);
    isHistoryAction.current = false;
    if (historyTimeoutRef.current) {
      clearTimeout(historyTimeoutRef.current);
    }
  }, [pageData?.source?.source_id, page]);

  useEffect(() => {
    return () => {
      if (historyTimeoutRef.current) {
        clearTimeout(historyTimeoutRef.current);
      }
    };
  }, []);

  const pushToHistory = (newVal) => {
    if (historyIndex < 0) return;
    const cleanHistory = history.slice(0, historyIndex + 1);
    if (cleanHistory[cleanHistory.length - 1] === newVal) return;
    
    const nextHistory = [...cleanHistory, newVal];
    if (nextHistory.length > 100) {
      nextHistory.shift();
      setHistory(nextHistory);
      setHistoryIndex(nextHistory.length - 1);
    } else {
      setHistory(nextHistory);
      setHistoryIndex(cleanHistory.length);
    }
  };

  const handleTextChange = (newVal) => {
    onTextChange(newVal);
    
    if (isHistoryAction.current) {
      isHistoryAction.current = false;
      return;
    }

    if (historyTimeoutRef.current) {
      clearTimeout(historyTimeoutRef.current);
    }
    historyTimeoutRef.current = setTimeout(() => {
      pushToHistory(newVal);
    }, 600);
  };

  const pushToHistoryImmediately = (newVal) => {
    if (historyTimeoutRef.current) {
      clearTimeout(historyTimeoutRef.current);
    }
    pushToHistory(newVal);
  };

  const handleUndo = () => {
    if (historyIndex > 0) {
      isHistoryAction.current = true;
      const prevText = history[historyIndex - 1];
      setHistoryIndex(historyIndex - 1);
      onTextChange(prevText);
    }
  };

  const handleRedo = () => {
    if (historyIndex < history.length - 1) {
      isHistoryAction.current = true;
      const nextText = history[historyIndex + 1];
      setHistoryIndex(historyIndex + 1);
      onTextChange(nextText);
    }
  };

  const handleKeyDown = (e) => {
    if (e.ctrlKey && !e.shiftKey && e.key === "z") {
      e.preventDefault();
      handleUndo();
    }
    if ((e.ctrlKey && e.key === "y") || (e.ctrlKey && e.shiftKey && e.key === "Z")) {
      e.preventDefault();
      handleRedo();
    }
  };

  const handleFindNext = () => {
    if (!searchTerm) return;
    const textarea = textareaRef.current;
    if (!textarea) return;

    const currentText = textarea.value;
    let searchPos = textarea.selectionEnd;

    let matchIdx = -1;
    let matchLen = searchTerm.length;

    if (useRegex) {
      try {
        const flags = caseSensitive ? "g" : "gi";
        const regex = new RegExp(searchTerm, flags);
        regex.lastIndex = searchPos;
        let match = regex.exec(currentText);
        if (!match) {
          regex.lastIndex = 0;
          match = regex.exec(currentText);
        }
        if (match) {
          matchIdx = match.index;
          matchLen = match[0].length;
        }
      } catch (err) {
        console.error("Invalid regex in Find Next", err);
      }
    } else {
      const textToSearch = caseSensitive ? currentText : currentText.toLowerCase();
      const termToSearch = caseSensitive ? searchTerm : searchTerm.toLowerCase();

      matchIdx = textToSearch.indexOf(termToSearch, searchPos);
      if (matchIdx === -1) {
        matchIdx = textToSearch.indexOf(termToSearch, 0);
      }
    }

    if (matchIdx !== -1) {
      textarea.focus();
      textarea.setSelectionRange(matchIdx, matchIdx + matchLen);
    }
  };

  // Handle Ctrl (or Shift) + Mouse Scroll to zoom in and out
  useEffect(() => {
    const wrap = pageWrapRef.current;
    if (!wrap) return;

    const handleWheel = (e) => {
      if (e.ctrlKey || e.shiftKey) {
        e.preventDefault();
        if (e.deltaY < 0) {
          // Zoom in
          setPageZoom((c) => Math.min(2.5, c + 0.15));
        } else {
          // Zoom out
          setPageZoom((c) => Math.max(0.2, c - 0.15));
        }
      }
    };

    wrap.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      wrap.removeEventListener("wheel", handleWheel);
    };
  }, [pageWrapRef, pageData?.source?.source_id, page]);

  const getHighlightRanges = (val) => {
    const ranges = [];
    const regex = /==([\s\S]*?)==/g;
    let match;
    while ((match = regex.exec(val)) !== null) {
      ranges.push({
        start: match.index,
        end: match.index + match[0].length,
        text: match[1]
      });
    }
    return ranges;
  };

  // Handle selected text inside the textarea
  const handleTextareaSelect = (e) => {
    const start = e.target.selectionStart;
    const end = e.target.selectionEnd;
    const val = e.target.value;
    const ranges = getHighlightRanges(val);

    const textBeforeCursor = val.substring(0, start);
    const linesBefore = textBeforeCursor.split("\n");
    const lineIndex = linesBefore.length - 1;

    // Calculate which ocrBlock corresponds to lineIndex in textarea
    const lines = val.split("\n");
    if (lineIndex >= 0 && lineIndex < lines.length && lines[lineIndex].trim() !== "") {
      // Count how many non-empty lines are before lineIndex
      let nonEmptyLineCount = 0;
      for (let i = 0; i < lineIndex; i++) {
        if (lines[i].trim() !== "") {
          nonEmptyLineCount++;
        }
      }

      // Find corresponding block index using the calculated mapping
      let blockIdx = -1;
      if (nonEmptyLineCount < blockLinesInfo.lineToBlock.length) {
        blockIdx = blockLinesInfo.lineToBlock[nonEmptyLineCount];
      }
      setActiveLineIndex(blockIdx);
    } else {
      setActiveLineIndex(-1);
    }

    if (start !== end) {
      // Validate selection: must not partially overlap any highlight range
      const isValid = ranges.every(r => {
        if (end <= r.start || start >= r.end) return true; // Completely outside
        if (start <= r.start && end >= r.end) return true; // Completely encloses
        return false; // Partial overlap
      });

      if (!isValid) {
        setSelectedHighlightText("");
      } else {
        setSelectedHighlightText(val.substring(start, end));
      }
      setClickedHighlight(null);
    } else {
      setSelectedHighlightText("");
      // Check if clicked inside a highlight block
      const clicked = ranges.find(r => start >= r.start && start <= r.end);
      if (clicked) {
        setClickedHighlight(clicked);
      } else {
        setClickedHighlight(null);
      }
    }
  };

  const handleHighlightSelection = () => {
    if (!selectedHighlightText.trim()) return;
    const textarea = textareaRef.current;
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    if (start === end) return;

    const ranges = getHighlightRanges(text);
    const isValid = ranges.every(r => {
      if (end <= r.start || start >= r.end) return true;
      if (start <= r.start && end >= r.end) return true;
      return false;
    });
    if (!isValid) return;

    const selected = text.substring(start, end);
    // Strip nested highlights inside the selection
    const cleanedSelected = selected.replace(/==/g, "");
    const highlighted = `==${cleanedSelected}==`;
    const newText = text.substring(0, start) + highlighted + text.substring(end);
    onTextChange(newText);
    pushToHistoryImmediately(newText);
    setSelectedHighlightText("");

    setTimeout(() => {
      textarea.focus();
      const newCursorPos = start + highlighted.length;
      textarea.setSelectionRange(newCursorPos, newCursorPos);
    }, 50);
  };

  const handleRemoveHighlight = () => {
    if (!clickedHighlight) return;
    const { start, end, text: inner } = clickedHighlight;
    const newText = text.substring(0, start) + inner + text.substring(end);
    onTextChange(newText);
    pushToHistoryImmediately(newText);
    setClickedHighlight(null);
  };

  const handleSearchReplace = (replaceAll = false) => {
    if (!searchTerm) return;
    let newText = text;
    try {
      if (useRegex) {
        const flags = (replaceAll ? "g" : "") + (caseSensitive ? "" : "i");
        const regex = new RegExp(searchTerm, flags);
        // Process Python-style backreferences (\1) and escapes (\n, \t) in replacement
        const processedReplace = replaceTerm
          .replace(/\\(\d+)/g, "$$$1")
          .replace(/\\n/g, "\n")
          .replace(/\\t/g, "\t")
          .replace(/\\r/g, "\r")
          .replace(/\\\\/g, "\\");
        newText = text.replace(regex, processedReplace);
      } else {
        if (replaceAll) {
          const escapedSearch = searchTerm.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
          const flags = "g" + (caseSensitive ? "" : "i");
          const regex = new RegExp(escapedSearch, flags);
          newText = text.replace(regex, replaceTerm);
        } else {
          const index = caseSensitive
            ? text.indexOf(searchTerm)
            : text.toLowerCase().indexOf(searchTerm.toLowerCase());
          if (index !== -1) {
            newText = text.substring(0, index) + replaceTerm + text.substring(index + searchTerm.length);
          }
        }
      }
      onTextChange(newText);
      pushToHistoryImmediately(newText);
    } catch (err) {
      alert("Regex error: " + err.message);
    }
  };

  const getHighlightedText = () => {
    let escapedText = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    if (searchTerm) {
      try {
        if (useRegex) {
          const flags = "g" + (caseSensitive ? "" : "i");
          const regex = new RegExp(`(${searchTerm})`, flags);
          escapedText = escapedText.replace(regex, "<mark>$1</mark>");
        } else {
          const escapedSearch = searchTerm.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
          const flags = "g" + (caseSensitive ? "" : "i");
          const regex = new RegExp(`(${escapedSearch})`, flags);
          escapedText = escapedText.replace(regex, "<mark>$1</mark>");
        }
      } catch (err) {
        // ignore search highlight issues
      }
    }

    // Convert markdown highlights ==text== and HTML-like highlights <mark>text</mark> to real <mark> tags in backdrop
    escapedText = escapedText.replace(/==([\s\S]*?)==/g, "<mark>$1</mark>");
    escapedText = escapedText.replace(/&lt;mark&gt;([\s\S]*?)&lt;\/mark&gt;/g, "<mark>$1</mark>");

    return escapedText;
  };

  const importPdf = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const msg = await onImportPdf(file);
      alert(msg);
    } catch (err) {
      alert("Failed to import PDF: " + err.message);
    }
  };

  const handleExportText = async (format) => {
    if (!source) return;
    const ok = window.confirm("WARNING: Please ensure all pages have completed OCR and any required manual edits or corrections have been saved before exporting. Proceed with export?");
    if (!ok) return;

    try {
      setTableMessage("Compiling and exporting source text...");
      const data = await fetchJson(`/api/v1/reading/sources/${source.source_id}/export-text`);
      let blob;
      let filename;
      if (format === "json") {
        blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        filename = `${source.source_id}_ocr_export.json`;
      } else if (format === "md") {
        blob = new Blob([data.markdown_text], { type: "text/markdown;charset=utf-8" });
        filename = `${source.source_id}_ocr_export.md`;
      } else {
        blob = new Blob([data.plain_text], { type: "text/plain;charset=utf-8" });
        filename = `${source.source_id}_ocr_export.txt`;
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setTableMessage("Export completed successfully.");
    } catch (err) {
      alert("Export failed: " + err.message);
      setTableMessage("Export failed: " + err.message);
    }
  };

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      pdfContainerRef.current?.requestFullscreen().catch((err) => {
        console.error("Fullscreen error", err);
      });
      setIsFullscreen(true);
    } else {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  };

  const activeRegion = regionDrag ? regionFromDrag(regionDrag.start, regionDrag.current) : region;

  const ocrDataSource = useMemo(() => {
    if (!pageData?.ocr) return null;
    const corrData = pageData.ocr.corrected_page_json_data;
    const rawData = pageData.ocr.raw_page_json_data;

    const corrBlocks = corrData?.contents ? corrData.contents.flatMap(b => Array.isArray(b) ? b : [b]) : [];
    const hasCorrBoxes = corrData?.imginfo?.img_width && corrBlocks.some(block => block && block.boundingBox && Array.isArray(block.boundingBox) && block.boundingBox.length >= 4);

    if (hasCorrBoxes) {
      return corrData;
    }
    if (rawData?.imginfo?.img_width) {
      return rawData;
    }
    return null;
  }, [pageData]);

  const ocrBlocks = useMemo(() => {
    const ocrData = ocrDataSource;
    if (!ocrData || !ocrData.contents) return [];

    const blocks = [];
    for (const block of ocrData.contents) {
      if (Array.isArray(block)) {
        for (const item of block) {
          if (item && typeof item === "object") {
            blocks.push(item);
          }
        }
      } else if (block && typeof block === "object") {
        blocks.push(block);
      }
    }
    return blocks;
  }, [ocrDataSource]);

  const hasBoundingBoxes = useMemo(() => {
    return ocrBlocks.some(block => block.boundingBox && Array.isArray(block.boundingBox) && block.boundingBox.length >= 4);
  }, [ocrBlocks]);

  const blockLinesInfo = useMemo(() => {
    const lineToBlock = []; // maps non-empty line index -> ocrBlock index
    const blockToLine = []; // maps ocrBlock index -> first non-empty line index of this block
    
    let nonEmptyLineCount = 0;
    for (let i = 0; i < ocrBlocks.length; i++) {
      const block = ocrBlocks[i];
      blockToLine[i] = nonEmptyLineCount;
      
      if (block && block.text && block.text.trim() !== "") {
        const blockLines = block.text.split("\n");
        let blockNonEmptyLines = 0;
        for (const line of blockLines) {
          if (line.trim() !== "") {
            lineToBlock.push(i);
            blockNonEmptyLines++;
          }
        }
        nonEmptyLineCount += blockNonEmptyLines;
      }
    }
    return { lineToBlock, blockToLine };
  }, [ocrBlocks]);

  const regionCoords = useMemo(() => {
    const ocrData = ocrDataSource;
    if (ocrData && ocrData.region_ocr && ocrData.region_ocr.region) {
      return ocrData.region_ocr.region;
    }
    return null;
  }, [ocrDataSource]);

  const getBoundingBoxStyle = (block) => {
    const ocrData = ocrDataSource;
    if (!ocrData || !ocrData.imginfo) return null;

    const imgWidth = ocrData.imginfo.img_width;
    const imgHeight = ocrData.imginfo.img_height;
    if (!imgWidth || !imgHeight) return null;

    const box = block.boundingBox;
    if (!box || !Array.isArray(box) || box.length < 4) return null;

    const xs = box.map(p => p[0]);
    const ys = box.map(p => p[1]);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);

    let leftRel = xMin / imgWidth;
    let topRel = yMin / imgHeight;
    let widthRel = (xMax - xMin) / imgWidth;
    let heightRel = (yMax - yMin) / imgHeight;

    if (regionCoords) {
      const rx = regionCoords.x || 0;
      const ry = regionCoords.y || 0;
      const rw = regionCoords.width || 1;
      const rh = regionCoords.height || 1;

      leftRel = rx + leftRel * rw;
      topRel = ry + topRel * rh;
      widthRel = widthRel * rw;
      heightRel = heightRel * rh;
    }

    return {
      left: `${leftRel * 100}%`,
      top: `${topRel * 100}%`,
      width: `${widthRel * 100}%`,
      height: `${heightRel * 100}%`
    };
  };

  const handleBoundingBoxClick = (idx) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const lines = text.split("\n");

    // Find the first non-empty line index of this block from the mapping
    const targetNonEmptyLineIdx = blockLinesInfo.blockToLine[idx];
    let textareaLineIdx = -1;
    
    if (targetNonEmptyLineIdx !== undefined) {
      let nonEmptyLineCount = 0;
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].trim() !== "") {
          if (nonEmptyLineCount === targetNonEmptyLineIdx) {
            textareaLineIdx = i;
            break;
          }
          nonEmptyLineCount++;
        }
      }
    }

    if (textareaLineIdx === -1) {
      // Fallback: if we can't align via mapping, just use idx if it's within range
      if (idx < lines.length) {
        textareaLineIdx = idx;
      } else {
        return;
      }
    }

    let startOffset = 0;
    for (let i = 0; i < textareaLineIdx; i++) {
      startOffset += lines[i].length + 1;
    }
    const endOffset = startOffset + lines[textareaLineIdx].length;

    textarea.focus();
    textarea.setSelectionRange(startOffset, endOffset);
    setActiveLineIndex(idx);

    const lineHeight = 20; 
    textarea.scrollTop = Math.max(0, textareaLineIdx * lineHeight - 100);
  };

  function regionPointFromEvent(event) {
    const frame = imageFrameRef.current;
    if (!frame) return null;
    const rect = frame.getBoundingClientRect();
    const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
    return { x, y };
  }

  function handlePointerDown(event) {
    if (!pageData?.source) return;
    if (pointerMode === "pan") {
      event.preventDefault(); // Prevent image dragging
      const wrap = pageWrapRef.current;
      if (!wrap) return;
      setPanDrag({
        startX: event.clientX,
        startY: event.clientY,
        scrollLeft: wrap.scrollLeft,
        scrollTop: wrap.scrollTop,
      });
      return;
    }
    // Crop mode
    const point = regionPointFromEvent(event);
    if (!point) return;
    setRegionResult(null);
    setRegionDrag({ start: point, current: point });
  }

  function handlePointerMove(event) {
    if (pointerMode === "pan") {
      if (!panDrag) return;
      const wrap = pageWrapRef.current;
      if (!wrap) return;
      const dx = event.clientX - panDrag.startX;
      const dy = event.clientY - panDrag.startY;
      wrap.scrollLeft = panDrag.scrollLeft - dx;
      wrap.scrollTop = panDrag.scrollTop - dy;
      return;
    }
    // Crop mode
    if (!regionDrag) return;
    const point = regionPointFromEvent(event);
    if (!point) return;
    setRegionDrag((current) => ({ ...current, current: point }));
  }

  function finishRegionSelection() {
    if (!regionDrag) return;
    const nextRegion = regionFromDrag(regionDrag.start, regionDrag.current);
    setRegionDrag(null);
    if (nextRegion.width < 0.02 || nextRegion.height < 0.02) {
      setTableMessage("Selected region is too small. Drag around the passage or table area you want to inspect.");
      return;
    }
    setRegion(nextRegion);
    setTableMessage("Region selected. Ready for Regional OCR or Cropping.");
  }

  function handlePointerUp() {
    if (pointerMode === "pan") {
      if (panDrag) setPanDrag(null);
      return;
    }
    finishRegionSelection();
  }

  async function cropSelectedRegion() {
    if (!pageData?.source || !activeRegion) {
      setTableMessage("Select a region on the page image first.");
      return;
    }
    setTableMessage("");
    try {
      const result = await fetchJson(`/api/v1/reading/sources/${pageData.source.source_id}/pages/${page}/regions`, {
        method: "POST",
        body: JSON.stringify({
          label: "selected region",
          region: activeRegion,
          rotation: pageRotation,
        }),
      });
      setRegion(result.region);
      setRegionResult(result);
      setRegionOcrResult(null);
      setTableMessage("Selected region saved for review.");
    } catch (err) {
      setTableMessage(err.message);
    }
  }

  async function ocrSelectedRegion(insertIntoText = true) {
    if (!pageData?.source || !activeRegion) {
      setTableMessage("Select a page region before running OCR.");
      return;
    }
    setTableMessage("");
    try {
      const effectiveEngine = parsingEngine === "__custom__" ? customParsingEngine : parsingEngine;
      const activeEngine = ocrEngines.find((e) => e.engine_id === effectiveEngine);
      const engineSettings: Record<string, any> = {};
      if (activeEngine?.options_schema) {
        activeEngine.options_schema.forEach((opt) => {
          const val = ocrSettings[opt.name] !== undefined ? ocrSettings[opt.name] : opt.default;
          engineSettings[opt.name] = val;
        });
      }
      const result = await fetchJson(`/api/v1/reading/sources/${pageData.source.source_id}/pages/${page}/regions/ocr`, {
        method: "POST",
        body: JSON.stringify({
          label: "selected region",
          region: regionResult?.region || activeRegion,
          region_id: regionResult?.region_id || regionResult?.region?.region_id || activeRegion?.region_id || "",
          crop_image: regionResult?.crop_image || "",
          ocr_mode: "text",
          parsing_engine: effectiveEngine,
          output_format: "text",
          rotation: pageRotation,
          ...engineSettings,
        }),
      });
      setRegionOcrResult(result);
      if (result.crop_image_url && !regionResult) {
        setRegionResult({
          region_id: result.region_id,
          region: { ...activeRegion, region_id: result.region_id },
          crop_image: result.crop_image,
          crop_image_url: result.crop_image_url,
        });
      }
      const nextText = result.text || "";
      if (insertIntoText) {
        const targetText = ocrInsertMode === "append" && text.trim() ? `${text.trimEnd()}\n\n${nextText}` : nextText;
        onTextChange(targetText);
        pushToHistoryImmediately(targetText);
      }
      setTableMessage(result.message || "Selected region OCR completed.");
      return result;
    } catch (err) {
      setTableMessage(err.message);
      return null;
    }
  }

  async function ocrWholePage(insertIntoText = true) {
    if (!pageData?.source) {
      setTableMessage("Choose a source and page before running whole-page OCR.");
      return null;
    }
    setTableMessage("");
    try {
      const effectiveEngine = parsingEngine === "__custom__" ? customParsingEngine : parsingEngine;
      const activeEngine = ocrEngines.find((e) => e.engine_id === effectiveEngine);
      const engineSettings: Record<string, any> = {};
      if (activeEngine?.options_schema) {
        activeEngine.options_schema.forEach((opt) => {
          const val = ocrSettings[opt.name] !== undefined ? ocrSettings[opt.name] : opt.default;
          engineSettings[opt.name] = val;
        });
      }
      const result = await fetchJson(`/api/v1/reading/sources/${pageData.source.source_id}/pages/${page}/ocr`, {
        method: "POST",
        body: JSON.stringify({
          parsing_engine: effectiveEngine,
          rotation: pageRotation,
          ...engineSettings,
        }),
      });
      setRegionOcrResult(result);
      const nextText = result.text || "";
      if (insertIntoText) {
        const targetText = ocrInsertMode === "append" && text.trim() ? `${text.trimEnd()}\n\n${nextText}` : nextText;
        onTextChange(targetText);
        pushToHistoryImmediately(targetText);
      }
      setTableMessage(result.message || "Whole-page OCR completed.");
      return result;
    } catch (err) {
      setTableMessage(err.message);
      return null;
    }
  }

  async function rerenderPage() {
    if (!pageData?.source) return;
    setPageImageError("");
    setTableMessage("");
    try {
      const result = await fetchJson(`/api/v1/reading/sources/${pageData.source.source_id}/pages/${page}/rerender`, { method: "POST" });
      setPageImageVersion((current) => current + 1);
      setTableMessage(result.message);
    } catch (err) {
      setPageImageError(err.message);
      setTableMessage(err.message);
    }
  }



  const rawOcrPath = pageData?.ocr?.raw_page_json || "";
  const correctedOcrPath = pageData?.ocr?.corrected_page_json || "";
  const sourceReady = Boolean(pageData?.source?.source_id);
  const pageReady = Boolean(page);
  const pageOptions = source?.ocr_pages || [];

  return (
    <div style={{ padding: "18px 22px 24px" }}>
      {/* Clean Top Bar */}
      <div className="readingDeskTopBar">
        <div className="readingDeskControls">
          <label>
            Source:
            <select value={source?.source_id || ""} onChange={(e) => onSourceChange(e.target.value)}>
              <option value="">Choose a source (Select or search via Choose Catalog)...</option>
              {sources.map((item) => (
                <option key={item.source_id} value={item.source_id}>
                  {item.title_original || item.title} ({item.source_id})
                </option>
              ))}
            </select>
          </label>
          {source && (
            <>
              <button
                className="quietButton light"
                type="button"
                onClick={() => onRenameSource(source.source_id)}
                title="Edit current source metadata & research notes"
                style={{ display: "flex", alignItems: "center", gap: 4 }}
              >
                <Settings size={14} /> Edit Metadata
              </button>
              <button
                className="quietButton light"
                type="button"
                onClick={() => onDeleteSource(source.source_id)}
                title="Delete current source permanently"
                style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--danger-color, #ef4444)" }}
              >
                <Trash2 size={14} /> Delete Source
              </button>
            </>
          )}
          <label className="quietButton light fileImportButton">
            <Upload size={15} /> Import PDF/ZIP
            <input type="file" accept="application/pdf,.pdf,application/zip,.zip" onChange={importPdf} />
          </label>
          {sourceReady && pageReady && (
            <>
              <button
                className="quietButton light"
                type="button"
                onClick={() => {
                  setPageImageVersion((v) => v + 1);
                  if (onReloadPage) onReloadPage();
                }}
                title="Reload page metadata and image"
                style={{ display: "flex", alignItems: "center", gap: 4 }}
              >
                <RotateCcw size={14} /> Reload Page
              </button>
              <a 
                className="quietButton light pdfLink" 
                href={`${API_BASE}/api/v1/reading/sources/${pageData.source.source_id}/pdf#page=${page}`} 
                target="_blank" 
                rel="noreferrer"
                style={{ display: "flex", alignItems: "center", gap: 4, textDecoration: "none", color: "inherit" }}
              >
                <FileText size={14} /> Open PDF
              </a>
            </>
          )}
        </div>
      </div>

      {/* Long Wide OCR Controls Toolbar on Top */}
      <div className="ocrControlPanelTop">
        <div className="ocrControlPanelSection">
          <label className="deskField compactDeskField" style={{ margin: 0 }}>
            <span>OCR Engine</span>
            <select
              value={parsingEngine}
              onChange={(e) => setParsingEngine(e.target.value)}
              style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)" }}
            >
              {(ocrEngines || []).map((eng) => {
                const engineId = typeof eng === "string" ? eng : (eng?.engine_id || "");
                const label = typeof eng === "string" ? eng : (eng?.label || engineId);
                return (
                  <option key={engineId} value={engineId}>
                    {label}
                  </option>
                );
              })}
              <option value="__custom__">+ Custom Engine...</option>
            </select>
          </label>
          {parsingEngine === "__custom__" && (
            <label className="deskField compactDeskField" style={{ margin: 0 }}>
              <span>Custom Engine Name</span>
              <input
                type="text"
                placeholder="e.g. ndlocr_lite"
                value={customParsingEngine}
                onChange={(e) => setCustomParsingEngine(e.target.value)}
                style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)" }}
              />
            </label>
          )}
          <label className="deskField compactDeskField" style={{ margin: 0 }}>
            <span>Insertion Mode</span>
            <select
              value={ocrInsertMode}
              onChange={(e) => setOcrInsertMode(e.target.value)}
              style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)" }}
            >
              <option value="replace">Replace Editor Text</option>
              <option value="append">Append Editor Text</option>
            </select>
          </label>
        </div>

        {/* Pointer Mode selection moved to pageImageToolbar */}



        <div className="ocrControlPanelActions">
          <button
            className="primaryButton"
            type="button"
            onClick={() => ocrWholePage(true)}
            disabled={!sourceReady || !pageReady}
          >
            Run Whole Page OCR
          </button>
          <button
            className="primaryButton"
            type="button"
            onClick={() => ocrSelectedRegion(true)}
            disabled={!sourceReady || !pageReady || !activeRegion}
          >
            Run Regional OCR
          </button>
          <button
            className="quietButton light"
            type="button"
            onClick={cropSelectedRegion}
            disabled={!sourceReady || !pageReady || !activeRegion}
            title="Save the current active crop selection to the server"
          >
            Save Page Crop
          </button>
          <button
            className="quietButton light"
            type="button"
            onClick={rerenderPage}
            disabled={!sourceReady || !pageReady}
            title="Re-render PDF page image"
            style={{ display: "flex", alignItems: "center", gap: 4 }}
          >
            <RotateCcw size={14} /> Re-render Page
          </button>
          <button
            className="quietButton light"
            type="button"
            onClick={() => handleExportText("txt")}
            disabled={!sourceReady}
            title="Export compiled OCR text of all pages in this source as plain text"
          >
            Export All TXT
          </button>
          <button
            className="quietButton light"
            type="button"
            onClick={() => handleExportText("md")}
            disabled={!sourceReady}
            title="Export compiled OCR text of all pages, metadata, and research notes as Markdown (.md)"
          >
            Export All MD
          </button>
          <button
            className="quietButton light"
            type="button"
            onClick={() => handleExportText("json")}
            disabled={!sourceReady}
            title="Export compiled OCR text of all pages in this source as JSON"
          >
            Export All JSON
          </button>
        </div>
      </div>

      <DynamicEngineSettings
        engineId={parsingEngine === "__custom__" ? customParsingEngine : parsingEngine}
        engines={ocrEngines}
        settings={ocrSettings}
        onChange={(name, val) => setOcrSettings((prev) => ({ ...prev, [name]: val }))}
        layout="horizontal"
      />

      {tableMessage && (
        <div className={`statusBanner ${isPositiveMessage(tableMessage) ? "success" : "info"}`} style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 6, fontSize: 13 }}>
          {tableMessage}
        </div>
      )}

      {/* Main Split Area */}
      <div className="ocrReviewSplit">
        <div className="ocrReviewSource">
          {pageData?.source ? (
            <div className="pdfViewerContainer" ref={pdfContainerRef}>
              <div className="pageImageToolbar">
                {sourceReady && (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginRight: 12 }}>
                    <label style={{ margin: 0, display: "flex", alignItems: "center", gap: 6, fontSize: "0.85rem", fontWeight: "700", color: "#344246" }}>
                      Page:
                      <select 
                        value={page} 
                        onChange={(e) => onPageChange(Number(e.target.value))}
                        style={{ padding: "4px 8px", borderRadius: 6, border: "1px solid #cfc7ba", background: "white", fontSize: "0.85rem", height: "30px" }}
                      >
                        {pageOptions.map((pageNumber) => (
                          <option key={pageNumber} value={pageNumber}>
                            Page {pageNumber}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                )}
                
                <div className="pointerModeToggle" style={{ display: "inline-flex", marginRight: 8 }}>
                  <button
                    type="button"
                    className={`toggleButton ${pointerMode === "crop" ? "active" : ""}`}
                    onClick={() => setPointerMode("crop")}
                    title="Crop Mode - Drag to select a page region"
                    style={{ padding: "4px 8px", display: "flex", alignItems: "center", gap: 4, height: "30px", borderTopRightRadius: 0, borderBottomRightRadius: 0 }}
                  >
                    <Crosshair size={14} /> Crop
                  </button>
                  <button
                    type="button"
                    className={`toggleButton ${pointerMode === "pan" ? "active" : ""}`}
                    onClick={() => setPointerMode("pan")}
                    title="Pan Mode - Click & drag to scroll page image"
                    style={{ padding: "4px 8px", display: "flex", alignItems: "center", gap: 4, height: "30px", borderTopLeftRadius: 0, borderBottomLeftRadius: 0, borderLeftWidth: 0 }}
                  >
                    <Hand size={14} /> Pan
                  </button>
                </div>

                {hasBoundingBoxes && (
                  <button
                    className="quietButton light"
                    type="button"
                    onClick={() => setShowBoundingBoxes(!showBoundingBoxes)}
                    title="Toggle OCR Bounding Boxes Overlay"
                    style={{ height: "30px", display: "inline-flex", alignItems: "center", gap: 4, marginRight: 8, padding: "0 8px", border: "1px solid #cfc7ba", borderRadius: 4, background: showBoundingBoxes ? "#eae3d5" : "transparent" }}
                  >
                    {showBoundingBoxes ? <Eye size={15} /> : <EyeOff size={15} />}
                    <span>Boxes</span>
                  </button>
                )}

                <button className="quietButton light" type="button" onClick={() => setPageRotation((current) => (current + 90) % 360)} style={{ height: "30px", display: "inline-flex", alignItems: "center" }}>
                  <RotateCw size={15} /> Rotate
                </button>
                
                <div style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <button className="quietButton light" type="button" onClick={() => setPageZoom((c) => Math.max(0.2, c - 0.15))} title="Zoom Out" style={{ height: "30px", width: "30px", padding: 0, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                    <ZoomOut size={15} />
                  </button>
                  <span style={{ fontSize: "0.8rem", color: "#605543", minWidth: "40px", textAlign: "center", userSelect: "none" }}>
                    {Math.round(pageZoom * 100)}%
                  </span>
                  <button className="quietButton light" type="button" onClick={() => setPageZoom((c) => Math.min(2.5, c + 0.15))} title="Zoom In" style={{ height: "30px", width: "30px", padding: 0, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                    <ZoomIn size={15} />
                  </button>
                </div>

                <button className="quietButton light" type="button" onClick={toggleFullscreen} title="Toggle Fullscreen" style={{ height: "30px", width: "30px", padding: 0, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                  {isFullscreen ? <Minimize size={15} /> : <Maximize size={15} />}
                </button>
              </div>
              <div className="pdfBodyContainer">
                <button
                  className="pdfSideNav prev"
                  type="button"
                  onClick={() => {
                    const pageIdx = pageOptions.indexOf(Number(page));
                    if (pageIdx > 0) onPageChange(pageOptions[pageIdx - 1]);
                  }}
                  disabled={pageOptions.indexOf(Number(page)) <= 0}
                  title="Previous Page"
                >
                  <ChevronLeft size={24} />
                </button>
                <div className="pageImageWrap" ref={pageWrapRef}>
                  <div
                    className={`pageImageFrame mode-${pointerMode}`}
                    ref={imageFrameRef}
                    style={{ width: `${pageZoom * 100}%` }}
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    onPointerLeave={handlePointerUp}
                  >
                    <img
                      className="pageImage"
                      alt={`Original page ${page}`}
                      src={`${API_BASE}/api/v1/reading/sources/${pageData.source.source_id}/pages/${page}/image?v=${pageImageVersion}&rotation=${pageRotation}`}
                      draggable="false"
                      onError={() => setPageImageError("Page image failed to load.")}
                      onLoad={() => setPageImageError("")}
                    />
                    {activeRegion && <div className="regionOverlay" style={regionStyle(activeRegion)} />}
                    {showBoundingBoxes && ocrBlocks.map((block, idx) => {
                      const rectStyle = getBoundingBoxStyle(block);
                      if (!rectStyle) return null;
                      const isHovered = hoveredLineIndex === idx;
                      const isActive = activeLineIndex === idx;
                      return (
                        <div
                          key={`bbox-${idx}`}
                          className={`ocrBoundingBox ${isHovered ? "hovered" : ""} ${isActive ? "active" : ""}`}
                          style={rectStyle}
                          onMouseEnter={() => setHoveredLineIndex(idx)}
                          onMouseLeave={() => setHoveredLineIndex(-1)}
                          onClick={() => handleBoundingBoxClick(idx)}
                          title={block.text}
                        />
                      );
                    })}
                  </div>
                  {pageImageError && (
                    <div className="errorBanner inline" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span>{pageImageError}</span>
                      <button
                        className="quietButton inline"
                        type="button"
                        onClick={() => {
                          setPageImageError("");
                          setPageImageVersion((v) => v + 1);
                          if (onReloadPage) onReloadPage();
                        }}
                        style={{ padding: "2px 8px", fontSize: 12, background: "rgba(255, 255, 255, 0.2)", border: "1px solid rgba(255,255,255,0.4)", borderRadius: 4, cursor: "pointer", color: "inherit" }}
                      >
                        Retry Load
                      </button>
                    </div>
                  )}
                </div>
                <button
                  className="pdfSideNav next"
                  type="button"
                  onClick={() => {
                    const pageIdx = pageOptions.indexOf(Number(page));
                    if (pageIdx !== -1 && pageIdx < pageOptions.length - 1) onPageChange(pageOptions[pageIdx + 1]);
                  }}
                  disabled={pageOptions.indexOf(Number(page)) === -1 || pageOptions.indexOf(Number(page)) >= pageOptions.length - 1}
                  title="Next Page"
                >
                  <ChevronRight size={24} />
                </button>
              </div>
            </div>
          ) : (
            <div className="emptyState">Choose a source to show page context.</div>
          )}
        </div>

        {/* OCR Text Box & Search/Replace Panel */}
        <div className="ocrReviewText">
          <div className="regexSearchReplaceBar">
            <div className="regexSearchReplaceRow">
              <input value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} placeholder="Search text..." type="text" />
              <input value={replaceTerm} onChange={(e) => setReplaceTerm(e.target.value)} placeholder="Replace with..." type="text" />
            </div>
            <div className="regexSearchReplaceRow">
              <label>
                <input type="checkbox" checked={useRegex} onChange={(e) => setUseRegex(e.target.checked)} />
                Regex
              </label>
              <label>
                <input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />
                Case sensitive
              </label>
              <button type="button" onClick={() => handleSearchReplace(false)}>Replace</button>
              <button type="button" onClick={() => handleSearchReplace(true)}>Replace All</button>
              <button type="button" onClick={handleFindNext} disabled={!searchTerm}>Find Next</button>
              
              <div style={{ display: "inline-flex", gap: 4, marginLeft: 8 }}>
                <button 
                  type="button" 
                  onClick={handleUndo} 
                  disabled={historyIndex <= 0}
                  title="Undo last edit (Ctrl+Z)"
                  style={{ height: "30px", width: "30px", padding: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "#f8f5ef", border: "1px solid #d9d3c8", borderRadius: 4, cursor: historyIndex > 0 ? "pointer" : "default" }}
                >
                  <Undo size={14} />
                </button>
                <button 
                  type="button" 
                  onClick={handleRedo} 
                  disabled={historyIndex >= history.length - 1}
                  title="Redo last edit (Ctrl+Y)"
                  style={{ height: "30px", width: "30px", padding: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "#f8f5ef", border: "1px solid #d9d3c8", borderRadius: 4, cursor: historyIndex < history.length - 1 ? "pointer" : "default" }}
                >
                  <Redo size={14} />
                </button>
              </div>
              
              <div style={{ flex: 1 }} />
              
              <span className="statusPill" style={{ padding: "4px 8px", fontSize: "0.8rem", height: "30px", display: "inline-flex", alignItems: "center" }}>
                {pageData?.ocr?.status || "No OCR"}
              </span>
              <button
                className="primaryButton saveOcrEditBtn"
                type="button"
                onClick={() => onSaveOcr({
                  ocr_page_json: rawOcrPath,
                  corrected_ocr_page_json: correctedOcrPath,
                })}
                disabled={!sourceReady || !pageReady || !text.trim()}
                style={{ minHeight: "30px", height: "30px", display: "inline-flex", alignItems: "center", gap: "6px", padding: "0 10px", fontSize: "0.82rem" }}
              >
                <Save size={13} /> Save OCR Edit
              </button>
            </div>
          </div>

          {selectedHighlightText && (
            <button className="highlightQuoteButton" type="button" onClick={handleHighlightSelection}>
              <Highlighter size={15} /> Highlight selection
            </button>
          )}

          {clickedHighlight && !selectedHighlightText && (
            <button className="highlightQuoteButton" type="button" onClick={handleRemoveHighlight} style={{ background: "#904738" }}>
              <X size={15} /> Remove highlight
            </button>
          )}

          <label className="deskField" style={{ flex: 1 }}>
            <span>Editable OCR text (Highlight text to format as a highlight)</span>
            <div className="ocrEditorContainer">
              <div 
                ref={backdropRef}
                className="ocrEditorHighlightBackdrop"
                dangerouslySetInnerHTML={{ __html: getHighlightedText() }}
              />
              <textarea
                className="ocrEditor"
                ref={textareaRef}
                value={text}
                onChange={(e) => handleTextChange(e.target.value)}
                onKeyDown={handleKeyDown}
                onSelect={handleTextareaSelect}
                onKeyUp={handleTextareaSelect}
                onMouseUp={handleTextareaSelect}
                onScroll={handleTextareaScroll}
                spellCheck="false"
                style={{ minHeight: 480 }}
              />
            </div>
          </label>

          {sourceReady && pageReady && (
            <label className="deskField" style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span>Page Research Note (included in exports)</span>
                <button
                  className="primaryButton"
                  type="button"
                  onClick={() => onSavePageNote(source.source_id, page, pageNoteText)}
                  style={{ minHeight: "24px", height: "24px", padding: "0 8px", fontSize: "0.75rem", borderRadius: 4 }}
                >
                  Save Page Note
                </button>
              </div>
              <textarea
                value={pageNoteText}
                onChange={(e) => onPageNoteTextChange(e.target.value)}
                placeholder="Enter context, translations, or annotations for this page..."
                style={{
                  minHeight: 100,
                  fontSize: "0.85rem",
                  padding: 8,
                  borderRadius: 6,
                  border: "1px solid var(--border-color)",
                  background: "var(--bg-surface-elevated, #fff)",
                  color: "var(--text-primary)",
                  resize: "vertical"
                }}
              />
            </label>
          )}

        </div>
      </div>
    </div>
  );
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function regionFromDrag(start, current) {
  const x1 = Math.min(start.x, current.x);
  const y1 = Math.min(start.y, current.y);
  const x2 = Math.max(start.x, current.x);
  const y2 = Math.max(start.y, current.y);
  return {
    unit: "relative",
    x: x1,
    y: y1,
    width: x2 - x1,
    height: y2 - y1,
  };
}

function regionStyle(region) {
  return {
    left: `${region.x * 100}%`,
    top: `${region.y * 100}%`,
    width: `${region.width * 100}%`,
    height: `${region.height * 100}%`,
  };
}

function uniqueBySourceId(records) {
  const seen = new Set();
  return records.filter((record) => {
    if (!record?.source_id || seen.has(record.source_id)) return false;
    seen.add(record.source_id);
    return true;
  });
}

function isPositiveMessage(message) {
  return /saved|imported|selected|completed|review|generated|created|rendered|promoted/i.test(message || "");
}

function SummaryBlock({ summary, loading }) {
  const counts = summary?.counts;
  return (
    <div className="summaryBlock">
      {loading || !counts ? (
        <span className="mutedOnDark">Loading evidence...</span>
      ) : (
        <>
          <Metric label="Entities" value={counts.entities} />
          <Metric label="Relations" value={counts.relationships} />
          <Metric label="Attitudes" value={counts.attitudes} />
          <Metric label="Quotes" value={counts.evidence_quotes} />
        </>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function TabButton({ active, icon, onClick, children }) {
  return (
    <button className={active ? "tabButton active" : "tabButton"} onClick={onClick} type="button">
      {icon}
      {children}
    </button>
  );
}

function PanelTitle({ icon, title }) {
  return (
    <div className="sectionTitle">
      {icon}
      <span>{title}</span>
    </div>
  );
}

function isGeneratedOfficerRecord(record) {
  return String(record?.entity_id || "").startsWith("officer_ent_")
    || String(record?.relationship_id || "").startsWith("officer_rel_")
    || String(record?.evidence_id || "").startsWith("officer_ev_");
}

function EntityTable({ entities, onOpenEntity, onEdit, onDelete }) {
  return (
    <div className="dataTableWrap">
      <table className="dataTable">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Aliases</th>
            <th>Sources</th>
            <th>Mentions</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {entities.map((entity) => {
            const readOnly = isGeneratedOfficerRecord(entity);
            return (
              <tr key={entity.entity_id} onClick={() => onOpenEntity(entity.entity_id)}>
                <td>
                  <strong>{entity.canonical_name}</strong>
                  <small>{entity.entity_id}</small>
                </td>
                <td>{entity.entity_type}</td>
                <td>{entity.aliases?.join(", ")}</td>
                <td>{entity.source_ids?.join(", ")}</td>
                <td>{entity.mention_count}</td>
                <td>
                  {readOnly ? (
                    <span className="readonlyPill">Generated</span>
                  ) : (
                    <div style={{ display: "flex", gap: "6px" }} onClick={(e) => e.stopPropagation()}>
                      <button className="editButtonSpreadsheet" onClick={() => onEdit(entity)}>Edit</button>
                      <button className="deleteButtonSpreadsheet" onClick={() => onDelete(entity)}>Delete</button>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {entities.length === 0 && <p className="muted">No matching entities.</p>}
    </div>
  );
}

function RelationshipTable({ claims, onOpenEvidence, onEdit, onDelete, onJumpToReadingDesk }) {
  return (
    <div className="dataTableWrap">
      <table className="dataTable">
        <thead>
          <tr>
            <th>Subject</th>
            <th>Relation</th>
            <th>Object</th>
            <th>Source</th>
            <th>Page</th>
            <th>Confidence</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((claim) => {
            const readOnly = isGeneratedOfficerRecord(claim);
            return (
              <tr key={claim.relationship_id} onClick={() => onOpenEvidence(claim.evidence_id)}>
                <td>{claim.subject_name}</td>
                <td>{claim.relation_type}</td>
                <td>{claim.object_name}</td>
                <td>{claim.source_id}</td>
                <td>{claim.page}</td>
                <td>{claim.confidence}</td>
                <td>
                  <div style={{ display: "flex", gap: "6px" }} onClick={(e) => e.stopPropagation()}>
                    {onJumpToReadingDesk && (
                      <button className="editButtonSpreadsheet" onClick={() => onJumpToReadingDesk(claim.source_id, claim.page, claim.quote)}>Locate</button>
                    )}
                    {readOnly ? (
                      <span className="readonlyPill">Generated</span>
                    ) : (
                      <>
                        <button className="editButtonSpreadsheet" onClick={() => onEdit(claim)}>Edit</button>
                        <button className="deleteButtonSpreadsheet" onClick={() => onDelete(claim)}>Delete</button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {claims.length === 0 && <p className="muted">No matching relationship claims.</p>}
    </div>
  );
}

function AttitudeTable({ claims, onOpenEvidence, onEdit, onDelete, onJumpToReadingDesk }) {
  return (
    <div className="dataTableWrap">
      <table className="dataTable">
        <thead>
          <tr>
            <th>Speaker</th>
            <th>Attitude</th>
            <th>Polarity</th>
            <th>Target</th>
            <th>Source</th>
            <th>Page</th>
            <th>Confidence</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((claim) => (
            <tr key={claim.attitude_id} onClick={() => onOpenEvidence(claim.evidence_id)}>
              <td>{claim.speaker_name}</td>
              <td>{claim.attitude_type}</td>
              <td>
                <span className={`polarity ${claim.polarity}`}>{claim.polarity}</span>
              </td>
              <td>{claim.target_name}</td>
              <td>{claim.source_id}</td>
              <td>{claim.page}</td>
              <td>{claim.confidence}</td>
              <td>
                <div style={{ display: "flex", gap: "6px" }} onClick={(e) => e.stopPropagation()}>
                  {onJumpToReadingDesk && (
                    <button className="editButtonSpreadsheet" onClick={() => onJumpToReadingDesk(claim.source_id, claim.page, claim.quote)}>Locate</button>
                  )}
                  <button className="editButtonSpreadsheet" onClick={() => onEdit(claim)}>Edit</button>
                  <button className="deleteButtonSpreadsheet" onClick={() => onDelete(claim)}>Delete</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {claims.length === 0 && <p className="muted">No matching attitude claims.</p>}
    </div>
  );
}

function EntityDetail({ detail, onOpenEvidence, onJumpToReadingDesk }) {
  if (!detail) {
    return (
      <section className="panel detailPanel">
        <PanelTitle icon={<Database size={18} />} title="Entity Detail" />
        <p className="muted">Select an entity to inspect mentions, relationships, attitudes, and evidence links.</p>
      </section>
    );
  }
  return (
    <section className="panel detailPanel">
      <PanelTitle icon={<Database size={18} />} title="Entity Detail" />
      <h1>{detail.entity.canonical_name}</h1>
      <p className="originalTitle">{detail.entity.entity_type}</p>
      <div className="tags">
        {detail.entity.aliases?.map((alias) => (
          <span key={alias}>{alias}</span>
        ))}
      </div>
      <h2>Mentions</h2>
      <div className="stack">
        {detail.mentions.map((mention) => (
          <div key={mention.mention_id} style={{ display: "flex", gap: 6, alignItems: "stretch" }}>
            <button className="rowButton" style={{ flex: 1 }} onClick={() => onOpenEvidence(mention.evidence_id)}>
              <strong>"{mention.name_as_appears}"</strong>
              {mention.quote && (
                <blockquote style={{ fontSize: "0.82rem", margin: "6px 0", borderLeft: "2px solid #cfc7ba", paddingLeft: "8px", color: "var(--text-secondary)", textAlign: "left" }}>
                  {mention.quote}
                </blockquote>
              )}
              <span>
                {mention.source_id}, page {mention.page}
              </span>
            </button>
            {onJumpToReadingDesk && (
              <button 
                title="Locate Quote in Reading Desk"
                onClick={() => onJumpToReadingDesk(mention.source_id, mention.page, mention.quote)}
                style={{
                  width: 36,
                  border: "1px solid var(--border-color)",
                  borderRadius: 6,
                  background: "var(--bg-surface-elevated)",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--color-primary, #284f54)"
                }}
              >
                <BookOpen size={15} />
              </button>
            )}
          </div>
        ))}
      </div>
      <h2>Relationships</h2>
      <div className="stack compact">
        {detail.relationships.map((claim) => (
          <div key={claim.relationship_id} style={{ display: "flex", gap: 6, alignItems: "stretch" }}>
            <button className="rowButton" style={{ flex: 1 }} onClick={() => onOpenEvidence(claim.evidence_id)}>
              <strong>{claim.relation_type}</strong>
              <span>
                {claim.source_id}, page {claim.page}
              </span>
            </button>
            {onJumpToReadingDesk && (
              <button 
                title="Locate Quote in Reading Desk"
                onClick={() => onJumpToReadingDesk(claim.source_id, claim.page, claim.quote)}
                style={{
                  width: 36,
                  border: "1px solid var(--border-color)",
                  borderRadius: 6,
                  background: "var(--bg-surface-elevated)",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--color-primary, #284f54)"
                }}
              >
                <BookOpen size={15} />
              </button>
            )}
          </div>
        ))}
      </div>
      <h2>Attitudes</h2>
      <div className="stack compact">
        {detail.attitudes.map((claim) => (
          <div key={claim.attitude_id} style={{ display: "flex", gap: 6, alignItems: "stretch" }}>
            <button className="rowButton" style={{ flex: 1 }} onClick={() => onOpenEvidence(claim.evidence_id)}>
              <strong>
                {claim.attitude_type} - {claim.polarity}
              </strong>
              <span>
                {claim.source_id}, page {claim.page}
              </span>
            </button>
            {onJumpToReadingDesk && (
              <button 
                title="Locate Quote in Reading Desk"
                onClick={() => onJumpToReadingDesk(claim.source_id, claim.page, claim.quote)}
                style={{
                  width: 36,
                  border: "1px solid var(--border-color)",
                  borderRadius: 6,
                  background: "var(--bg-surface-elevated)",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--color-primary, #284f54)"
                }}
              >
                <BookOpen size={15} />
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function EvidenceDrawer({ evidence, onClose, onJumpToReadingDesk }) {
  return (
    <aside className="evidenceDrawer" aria-label="Evidence detail">
      <div className="drawerHeader">
        <div>
          <span className="eyebrow">Evidence</span>
          <h2>{evidence.evidence_id}</h2>
        </div>
        <button className="iconButton" onClick={onClose} aria-label="Close evidence drawer">
          <X size={18} />
        </button>
      </div>
      <blockquote>{evidence.quote}</blockquote>
      {onJumpToReadingDesk && (
        <button 
          className="primaryButton" 
          onClick={() => onJumpToReadingDesk(evidence.source_id, evidence.page, evidence.quote)}
          style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, marginBottom: 16 }}
        >
          <BookOpen size={16} />
          Locate in Reading Desk
        </button>
      )}
      <dl className="drawerMeta">
        <div>
          <dt>Source</dt>
          <dd>{evidence.source_id}</dd>
        </div>
        <div>
          <dt>Page</dt>
          <dd>{evidence.page}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{evidence.extraction_status}</dd>
        </div>
        <div>
          <dt>OCR JSON</dt>
          <dd>{evidence.ocr_page_json}</dd>
        </div>
        <div>
          <dt>Local PDF</dt>
          <dd>{evidence.source_pdf}</dd>
        </div>
        <div>
          <dt>Note</dt>
          <dd>{evidence.note || "-"}</dd>
        </div>
      </dl>
    </aside>
  );
}

function selectedTextOrFallback(text) {
  const selected = window.getSelection?.().toString().trim();
  if (selected) return selected;
  return text.split("\n").find((line) => line.trim()) || text.slice(0, 240);
}

function uniqueValues(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function matchesQuery(value, query) {
  if (!query.trim()) return true;
  return JSON.stringify(value).toLowerCase().includes(query.trim().toLowerCase());
}


function EvidenceDesk({
  sources,
  initialSourceId,
  onSourceChange,
  allEntities,
  onRefresh,
  onSaveEvidence,
  entityTypes,
  setEntityTypes,
  relationTypes,
  setRelationTypes,
  onJumpToReadingDesk,
  onMergeTrigger,
}) {
  const [selectedSourceId, setSelectedSourceId] = useState(initialSourceId || "");
  const [artifact, setArtifact] = useState(null);
  const [activeQuote, setActiveQuote] = useState(null);
  const [selectedText, setSelectedText] = useState("");
  const [graphMessage, setGraphMessage] = useState("");

  const handleLocateQuote = (quote) => {
    setActiveQuote(quote);
    setSelectedText("");
    setSelectedNodeEntity(null);
    setSelectedEdgeRelation(null);
    setTimeout(() => {
      document.getElementById(`quote_card_${quote.evidence_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);
  };
  
  // Entity Approval States
  const [entityModalOpen, setEntityModalOpen] = useState(false);
  const [entityModalMode, setEntityModalMode] = useState("create"); // 'create' or 'link'
  const [newEntity, setNewEntity] = useState({ canonical_name: "", name_original: "", entity_type: "person", aliasesString: "", notes: "" });
  const [linkToEntityId, setLinkToEntityId] = useState("");
  const [selectedEvidenceId, setSelectedEvidenceId] = useState("");

  // Graph state (Node coordinates map)
  const [positions, setPositions] = useState({});
  const [draggedNodeId, setDraggedNodeId] = useState(null);
  const [drawingEdgeFromId, setDrawingEdgeFromId] = useState(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  // Relationship Modal States
  const [relModalOpen, setRelModalOpen] = useState(false);
  const [newRel, setNewRel] = useState({ subject_id: "", object_id: "", relation_type: "spouse", note: "", confidence: "medium", evidence_id: "" });

  // Node editing state
  const [selectedNodeEntity, setSelectedNodeEntity] = useState(null);
  const [selectedEdgeRelation, setSelectedEdgeRelation] = useState(null);

  useEffect(() => {
    if (selectedSourceId) {
      loadArtifact(selectedSourceId);
    } else {
      setArtifact(null);
      setActiveQuote(null);
    }
  }, [selectedSourceId]);

  async function loadArtifact(sourceId) {
    setGraphMessage("");
    try {
      const art = await fetchJson(`/api/v1/evidence/source-graph/${sourceId}`);
      const hasGeneratedOfficerRows = (art.relationship_claims || []).some((claim) => String(claim.relationship_id || "").startsWith("officer_rel_"))
        || (art.evidence_quotes || []).some((quote) => String(quote.evidence_id || "").startsWith("officer_ev_"));
      if (!hasGeneratedOfficerRows) {
        try {
          const editableArt = await fetchJson(`/api/v1/extraction-artifacts/${sourceId}`);
          if (editableArt.extraction_schema_version === "evidence-graph-v1") {
            setArtifact({ ...editableArt, read_only: false, data_source: "editable_json" });
            setActiveQuote(null);
            initializeGraphPositions(editableArt.entity_records || []);
            return;
          }
        } catch {
          // Keep the generated SQLite graph below.
        }
      }
      setArtifact(art);
      setActiveQuote(null);
      initializeGraphPositions(art.entity_records || []);
      if ((art.entity_records || []).length === 0 && (art.relationship_claims || []).length === 0 && (art.evidence_quotes || []).length === 0) {
        setGraphMessage("No queryable evidence graph rows found for this source. Rebuild SQLite or check review status.");
      }
    } catch (err) {
      try {
        const art = await fetchJson(`/api/v1/extraction-artifacts/${sourceId}`);
        setArtifact({ ...art, read_only: false, data_source: "editable_json" });
        setActiveQuote(null);
        initializeGraphPositions(art.entity_records || []);
        setGraphMessage("Loaded editable JSON artifact because the generated SQLite graph was unavailable.");
      } catch {
        setArtifact(null);
        setActiveQuote(null);
        setPositions({});
        setGraphMessage(`Unable to load graph for this source: ${err.message}`);
      }
    }
  }

  function initializeGraphPositions(entities) {
    const newPos = {};
    entities.forEach((entity, idx) => {
      const angle = (idx / (entities.length || 1)) * 2 * Math.PI;
      newPos[entity.entity_id] = {
        x: 250 + 150 * Math.cos(angle),
        y: 200 + 120 * Math.sin(angle),
      };
    });
    setPositions(newPos);
  }

  const handleDeleteQuote = async (evidenceId) => {
    if (artifact?.read_only) {
      alert("This graph is generated from SQLite/reviewed artifacts. Edit the source artifact or table review data, then rebuild the database.");
      return;
    }
    const confirm = window.confirm("Are you sure you want to delete this quote? Any entity mentions, relationships, or claims linked to this quote will also be deleted.");
    if (!confirm) return;
    try {
      const matchingQuote = quotes.find(q => q.evidence_id === evidenceId);
      const targetSourceId = selectedSourceId === "project"
        ? (matchingQuote?.source_id || sources[0]?.source_id)
        : selectedSourceId;

      await fetchJson(`/api/v1/evidence/quotes?evidence_id=${evidenceId}&source_id=${targetSourceId}`, {
        method: "DELETE"
      });
      if (activeQuote?.evidence_id === evidenceId) {
        setActiveQuote(null);
        setSelectedText("");
      }
      await loadArtifact(selectedSourceId);
      await onRefresh();
    } catch (err) {
      alert("Failed to delete quote: " + err.message);
    }
  };

  // Handle highlighted text inside the quote text display
  const handleQuoteTextSelect = (e) => {
    const selected = window.getSelection().toString().trim();
    if (selected) {
      setSelectedText(selected);
    }
  };

  const handleRecognizeAsEntity = () => {
    if (artifact?.read_only) return;
    if (!selectedText.trim()) return;
    setNewEntity({
      canonical_name: selectedText,
      name_original: selectedText,
      entity_type: "person",
      aliasesString: "",
      notes: ""
    });
    setLinkToEntityId("");
    setSelectedEvidenceId(activeQuote?.evidence_id || "");
    setEntityModalMode("create");
    setEntityModalOpen(true);
  };

  const handleSaveEntityApproval = async () => {
    try {
      let entityId = "";
      const matchingQuote = selectedEvidenceId ? quotes.find(q => q.evidence_id === selectedEvidenceId) : null;
      const targetSourceId = selectedSourceId === "project"
        ? (matchingQuote?.source_id || sources[0]?.source_id)
        : selectedSourceId;

      if (entityModalMode === "create") {
        entityId = `ent_${Date.now()}`;
        // Add entity to current artifact
        await fetchJson("/api/v1/evidence/entities", {
          method: "PUT",
          body: JSON.stringify({
            source_id: targetSourceId,
            entity_id: entityId,
            canonical_name: newEntity.canonical_name,
            name_original: newEntity.name_original,
            entity_type: newEntity.entity_type,
            aliases: newEntity.aliasesString.split(",").map(a => a.trim()).filter(Boolean),
            notes: newEntity.notes
          })
        });
      } else {
        entityId = linkToEntityId;
        if (!entityId) return;
      }

      // Add Mention (Entity Mention) linking entity to selectedEvidenceId
      if (selectedEvidenceId && matchingQuote) {
        const mentionName = selectedText || newEntity.canonical_name || "Mention";
        await fetchJson("/api/v1/evidence/mentions", {
          method: "PUT",
          body: JSON.stringify({
            source_id: targetSourceId,
            entity_id: entityId,
            page: matchingQuote.page,
            name_as_appears: mentionName,
            evidence_id: matchingQuote.evidence_id,
            confidence: "medium",
            note: `Mention of ${mentionName} recognized from quote.`
          })
        });
      }

      setEntityModalOpen(false);
      setSelectedText("");
      await loadArtifact(selectedSourceId);
      await onRefresh();
    } catch (err) {
      alert("Failed to approve entity: " + err.message);
    }
  };

  // Dragging nodes handlers
  const handleNodeMouseDown = (e, entityId) => {
    e.stopPropagation();
    if (artifact?.read_only) return;
    if (e.shiftKey) {
      // Draw edge start
      setDrawingEdgeFromId(entityId);
      const rect = e.currentTarget.ownerSVGElement.getBoundingClientRect();
      setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    } else {
      setDraggedNodeId(entityId);
    }
  };

  const handleCanvasMouseMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    if (draggedNodeId && positions[draggedNodeId]) {
      setPositions({
        ...positions,
        [draggedNodeId]: { x, y }
      });
    } else if (drawingEdgeFromId) {
      setMousePos({ x, y });
    }
  };

  const handleCanvasMouseUp = () => {
    setDraggedNodeId(null);
    setDrawingEdgeFromId(null);
  };

  const handleNodeMouseUp = (e, entityId) => {
    if (artifact?.read_only) return;
    if (drawingEdgeFromId && drawingEdgeFromId !== entityId) {
      // Connect nodes! Open Relationship Modal
      setNewRel({
        subject_id: drawingEdgeFromId,
        object_id: entityId,
        relation_type: "spouse",
        note: "",
        confidence: "medium",
        evidence_id: activeQuote?.evidence_id || (quotes[0]?.evidence_id || "")
      });
      setRelModalOpen(true);
    }
    setDrawingEdgeFromId(null);
  };

  const handleSaveRelationship = async () => {
    if (artifact?.read_only) {
      alert("This graph is generated from SQLite/reviewed artifacts. Edit the source artifact or table review data, then rebuild the database.");
      return;
    }
    if (!newRel.evidence_id) {
      alert("Please select an evidence quote for this relationship.");
      return;
    }
    const matchingQuote = quotes.find(q => q.evidence_id === newRel.evidence_id);
    if (!matchingQuote) {
      alert("Selected evidence quote not found.");
      return;
    }

    try {
      const subjectNode = nodes.find(n => n.entity_id === newRel.subject_id);
      const objectNode = nodes.find(n => n.entity_id === newRel.object_id);
      const targetSourceId = selectedSourceId === "project"
        ? (matchingQuote?.source_id || sources[0]?.source_id)
        : selectedSourceId;

      await fetchJson("/api/v1/evidence/relationships", {
        method: "PUT",
        body: JSON.stringify({
          source_id: targetSourceId,
          relation_type: newRel.relation_type,
          page: matchingQuote.page,
          evidence_id: matchingQuote.evidence_id,
          quote: matchingQuote.quote,
          confidence: newRel.confidence,
          note: newRel.note,
          subject: {
            entity_id: newRel.subject_id,
            name: subjectNode?.canonical_name || "",
            entity_type: subjectNode?.entity_type || "person"
          },
          object: {
            entity_id: newRel.object_id,
            name: objectNode?.canonical_name || "",
            entity_type: objectNode?.entity_type || "person"
          }
        })
      });
      setRelModalOpen(false);
      await loadArtifact(selectedSourceId);
      await onRefresh();
    } catch (err) {
      alert("Failed to create relationship: " + err.message);
    }
  };

  const handleUpdateNodeEntity = async () => {
    if (artifact?.read_only) {
      alert("This graph is generated from SQLite/reviewed artifacts. Edit the source artifact or table review data, then rebuild the database.");
      return;
    }
    if (!selectedNodeEntity) return;
    try {
      const matchingMention = artifact?.entity_mentions?.find(m => m.entity_id === selectedNodeEntity.entity_id);
      const targetSourceId = selectedSourceId === "project"
        ? (matchingMention?.source_id || selectedNodeEntity.source_id || sources[0]?.source_id)
        : selectedSourceId;

      await fetchJson("/api/v1/evidence/entities", {
        method: "PUT",
        body: JSON.stringify({
          source_id: targetSourceId,
          ...selectedNodeEntity
        })
      });
      setSelectedNodeEntity(null);
      await loadArtifact(selectedSourceId);
      await onRefresh();
    } catch (err) {
      alert("Failed to update entity: " + err.message);
    }
  };

  const handleDeleteNodeEntity = async () => {
    if (artifact?.read_only) {
      alert("This graph is generated from SQLite/reviewed artifacts. Edit the source artifact or table review data, then rebuild the database.");
      return;
    }
    if (!selectedNodeEntity) return;
    const confirm = window.confirm("Delete this entity? Mentions and relationships using it will also be deleted.");
    if (!confirm) return;
    try {
      const targetSourceId = selectedSourceId === "project" ? "" : selectedSourceId;
      const query = targetSourceId ? `&source_id=${targetSourceId}` : "";
      await fetchJson(`/api/v1/evidence/entities?entity_id=${selectedNodeEntity.entity_id}${query}`, {
        method: "DELETE"
      });
      setSelectedNodeEntity(null);
      await loadArtifact(selectedSourceId);
      await onRefresh();
    } catch (err) {
      alert("Failed to delete entity: " + err.message);
    }
  };

  const handleUpdateEdgeRelation = async () => {
    if (artifact?.read_only) {
      alert("This graph is generated from SQLite/reviewed artifacts. Edit the source artifact or table review data, then rebuild the database.");
      return;
    }
    if (!selectedEdgeRelation) return;
    try {
      const subjectNode = nodes.find(n => n.entity_id === selectedEdgeRelation.subject_entity_id);
      const objectNode = nodes.find(n => n.entity_id === selectedEdgeRelation.object_entity_id);
      const targetSourceId = selectedSourceId === "project"
        ? (selectedEdgeRelation.source_id || sources[0]?.source_id)
        : selectedSourceId;

      await fetchJson("/api/v1/evidence/relationships", {
        method: "PUT",
        body: JSON.stringify({
          source_id: targetSourceId,
          relationship_id: selectedEdgeRelation.relationship_id,
          relation_type: selectedEdgeRelation.relation_type,
          page: selectedEdgeRelation.page,
          evidence_id: selectedEdgeRelation.evidence_id,
          quote: selectedEdgeRelation.quote,
          confidence: selectedEdgeRelation.confidence,
          note: selectedEdgeRelation.note,
          subject: {
            entity_id: selectedEdgeRelation.subject_entity_id,
            name: subjectNode?.canonical_name || "",
            entity_type: subjectNode?.entity_type || "person"
          },
          object: {
            entity_id: selectedEdgeRelation.object_entity_id,
            name: objectNode?.canonical_name || "",
            entity_type: objectNode?.entity_type || "person"
          }
        })
      });
      setSelectedEdgeRelation(null);
      await loadArtifact(selectedSourceId);
      await onRefresh();
    } catch (err) {
      alert("Failed to update relationship: " + err.message);
    }
  };

  const handleDeleteEdgeRelation = async () => {
    if (artifact?.read_only) {
      alert("This graph is generated from SQLite/reviewed artifacts. Edit the source artifact or table review data, then rebuild the database.");
      return;
    }
    if (!selectedEdgeRelation) return;
    const confirmDelete = window.confirm("Are you sure you want to delete this relationship?");
    if (!confirmDelete) return;

    try {
      const targetSourceId = selectedSourceId === "project"
        ? (selectedEdgeRelation.source_id || sources[0]?.source_id)
        : selectedSourceId;

      await fetchJson(`/api/v1/evidence/relationships?relationship_id=${selectedEdgeRelation.relationship_id}&source_id=${targetSourceId}`, {
        method: "DELETE"
      });
      setSelectedEdgeRelation(null);
      await loadArtifact(selectedSourceId);
      await onRefresh();
    } catch (err) {
      alert("Failed to delete relationship: " + err.message);
    }
  };

  const nodes = artifact?.entity_records || [];
  const edges = artifact?.relationship_claims || [];
  const quotes = artifact?.evidence_quotes || [];
  const graphReadOnly = Boolean(artifact?.read_only);
  const selectedSource = sources.find(s => s.source_id === selectedSourceId);
  const sourceTitle = selectedSource?.title_original || selectedSource?.title || selectedSourceId;

  return (
    <div className="evidenceDeskLayout">
      <div className="quotesListPanel">
        <label className="deskField">
          <span>Active Source</span>
          <select value={selectedSourceId} onChange={(e) => {
            setSelectedSourceId(e.target.value);
            onSourceChange(e.target.value);
          }}>
            <option value="">Choose a source</option>
            <option value="project">Project View (All Sources)</option>
            {sources.map((s) => (
              <option key={s.source_id} value={s.source_id}>
                {s.title_original || s.title} ({s.source_id})
              </option>
            ))}
          </select>
        </label>
        {selectedSourceId && (
          <>
            {graphReadOnly && (
              <div className="warningBanner" style={{ marginBottom: 12 }}>
                Generated from SQLite/reviewed artifacts. Edit the source artifact or table review data, then rebuild the database.
              </div>
            )}
            {graphMessage && (
              <div className="emptyState" style={{ marginBottom: 12 }}>
                {graphMessage}
              </div>
            )}
            {activeQuote && (
              <div className="quoteViewerContainer" style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <h4 style={{ margin: 0 }}>Quote Viewer (Highlight text to extract entity)</h4>
                  {!graphReadOnly && (
                    <button 
                      className="quietButton light dangerButton" 
                      onClick={() => handleDeleteQuote(activeQuote.evidence_id)}
                      style={{ padding: "4px 8px", fontSize: "0.8rem", height: "auto" }}
                    >
                      Delete Quote
                    </button>
                  )}
                </div>
                <div className="quoteTextDisplay" onMouseUp={handleQuoteTextSelect}>
                  {activeQuote.quote}
                </div>
                {selectedText && !graphReadOnly && (
                  <button className="primaryButton" onClick={handleRecognizeAsEntity}>
                    Recognize "{selectedText}" as Entity
                  </button>
                )}
              </div>
            )}

            <h3>Saved Quotes ({quotes.length})</h3>
            <div className="quotesStack" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {quotes.map((q) => (
                <div 
                  id={`quote_card_${q.evidence_id}`}
                  key={q.evidence_id} 
                  className={`quoteCard ${activeQuote?.evidence_id === q.evidence_id ? "active" : ""}`}
                  onClick={() => {
                    setActiveQuote(q);
                    setSelectedText("");
                  }}
                >
                  <div className="quoteCardHeader">
                    <span>{sourceTitle} ({q.evidence_id.split('_').pop().toUpperCase()})</span>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <span>Page {q.page}</span>
                      {onJumpToReadingDesk && (
                        <button
                          title="Open Page in Reading Desk"
                          onClick={(e) => {
                            e.stopPropagation();
                            onJumpToReadingDesk(selectedSourceId, q.page);
                          }}
                          style={{
                            background: "transparent",
                            border: "none",
                            color: "#284f54",
                            cursor: "pointer",
                            padding: "2px 4px",
                            display: "flex",
                            alignItems: "center"
                          }}
                        >
                          <BookOpen size={13} />
                        </button>
                      )}
                      {!graphReadOnly && (
                        <button
                          title="Delete Quote"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteQuote(q.evidence_id);
                          }}
                          style={{
                            background: "transparent",
                            border: "none",
                            color: "#ef4444",
                            cursor: "pointer",
                            padding: "2px 4px",
                            display: "flex",
                            alignItems: "center"
                          }}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="quoteCardBody">{q.quote}</div>
                </div>
              ))}
              {quotes.length === 0 && <p className="muted">No evidence quotes saved for this source yet.</p>}
            </div>
          </>
        )}
      </div>

      {/* Right panel: SVG Interactive Graph Canvas */}
      <div className="panel svgGraphPanel">
        <div className="svgGraphHeader">
          <div>
            <h3>Evidence Graph Workspace</h3>
            <div className="graphInstructions">
              {graphReadOnly
                ? "Generated graph view is read-only. Select nodes or edges to inspect evidence and provenance."
                : "Shift+Drag from a node to another to create relationship. Double-click canvas to create new node."}
            </div>
          </div>
        </div>

        {selectedSourceId ? (
          <div className="svgGraphWrapper">
            <svg 
              className="svgGraphCanvas"
              onMouseMove={handleCanvasMouseMove}
              onMouseUp={handleCanvasMouseUp}
              onDoubleClick={async (e) => {
                if (graphReadOnly) return;
                if (e.target === e.currentTarget) {
                  const rect = e.currentTarget.getBoundingClientRect();
                  const x = e.clientX - rect.left;
                  const y = e.clientY - rect.top;
                  const newId = `ent_${Date.now()}`;
                  
                  // Open modal for new entity creation
                  setNewEntity({ canonical_name: "New Entity", name_original: "New Entity", entity_type: "person", aliasesString: "", notes: "" });
                  setSelectedEvidenceId(activeQuote?.evidence_id || "");
                  setEntityModalMode("create");
                  setEntityModalOpen(true);
                  
                  // Temporarily place coordinate
                  setPositions({ ...positions, [newId]: { x, y } });
                }
              }}
            >
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="17" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#5c686a" />
                </marker>
              </defs>

              {/* Edge claims */}
              {edges.map((edge) => {
                const subPos = positions[edge.subject_entity_id];
                const objPos = positions[edge.object_entity_id];
                if (!subPos || !objPos) return null;

                const dx = objPos.x - subPos.x;
                const dy = objPos.y - subPos.y;
                const midX = (subPos.x + objPos.x) / 2;
                const midY = (subPos.y + objPos.y) / 2;

                return (
                  <g 
                    key={edge.relationship_id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSelectedEdgeRelation(edge)}
                  >
                    <line 
                      x1={subPos.x} 
                      y1={subPos.y} 
                      x2={objPos.x} 
                      y2={objPos.y} 
                      className="graphEdge"
                      markerEnd="url(#arrow)"
                    />
                    <text 
                      x={midX} 
                      y={midY - 8} 
                      className="edgeLabel"
                      textAnchor="middle"
                    >
                      {edge.relation_type}
                    </text>
                  </g>
                );
              })}

              {/* Drawing temporary Edge claim */}
              {drawingEdgeFromId && positions[drawingEdgeFromId] && (
                <line 
                  x1={positions[drawingEdgeFromId].x} 
                  y1={positions[drawingEdgeFromId].y} 
                  x2={mousePos.x} 
                  y2={mousePos.y} 
                  style={{ stroke: "#7d3d2f", strokeWidth: 2, strokeDasharray: "4 4" }}
                />
              )}

              {/* Nodes */}
              {nodes.map((node) => {
                const pos = positions[node.entity_id] || { x: 100, y: 100 };
                const nodeColors = { person: "#ffd700", place: "#90ee90", organization: "#add8e6" };
                const fill = nodeColors[node.entity_type] || "#ffffff";

                return (
                  <g 
                    key={node.entity_id}
                    transform={`translate(${pos.x}, ${pos.y})`}
                    className="graphNode"
                    onMouseDown={(e) => handleNodeMouseDown(e, node.entity_id)}
                    onMouseUp={(e) => handleNodeMouseUp(e, node.entity_id)}
                    onClick={() => {
                      setSelectedNodeEntity({
                        ...node,
                        aliasesString: node.aliases?.join(", ") || ""
                      });
                    }}
                  >
                    <circle 
                      r="16" 
                      fill={fill} 
                      stroke="#394649" 
                      strokeWidth="1.5"
                    />
                    <text 
                      y="26" 
                      className="nodeText"
                    >
                      {node.canonical_name}
                    </text>
                    {/* Small dragging handle handle */}
                    <circle 
                      cx="12" 
                      cy="-12" 
                      r="4" 
                      className="nodeHandle"
                    >
                      <title>Shift+Drag to connect</title>
                    </circle>
                  </g>
                );
              })}
            </svg>
          </div>
        ) : (
          <div className="emptyState">Select a source project on the left to activate workspace.</div>
        )}
      </div>

      {/* Entity modal (create/link) */}
      {entityModalOpen && (
        <div className="customModalOverlay">
          <div className="customModal">
            <h3 className="customModalTitle">Approve Entity Mention</h3>
            <div className="editorToolbar" style={{ marginBottom: 12 }}>
              <button 
                className={`quietButton light ${entityModalMode === "create" ? "active" : ""}`}
                onClick={() => setEntityModalMode("create")}
              >
                Create New Entity
              </button>
              <button 
                className={`quietButton light ${entityModalMode === "link" ? "active" : ""}`}
                onClick={() => setEntityModalMode("link")}
              >
                Link to Existing Entity
              </button>
            </div>

            {entityModalMode === "create" ? (
              <div className="customModalBody">
                <label className="deskField">
                  <span>Canonical Name</span>
                  <input 
                    type="text" 
                    value={newEntity.canonical_name}
                    onChange={(e) => setNewEntity({ ...newEntity, canonical_name: e.target.value })}
                  />
                </label>
                <CategorySelector
                  label="Type"
                  value={newEntity.entity_type}
                  onChange={(val) => setNewEntity({ ...newEntity, entity_type: val })}
                  types={entityTypes}
                  setTypes={setEntityTypes}
                  isEntity={true}
                />
                <label className="deskField">
                  <span>Aliases (comma separated)</span>
                  <input 
                    type="text" 
                    value={newEntity.aliasesString}
                    onChange={(e) => setNewEntity({ ...newEntity, aliasesString: e.target.value })}
                  />
                </label>
              </div>
            ) : (
              <div className="customModalBody">
                <label className="deskField">
                  <span>Select Entity</span>
                  <select 
                    value={linkToEntityId}
                    onChange={(e) => setLinkToEntityId(e.target.value)}
                  >
                    <option value="">Choose entity...</option>
                    {nodes.map(n => (
                      <option key={n.entity_id} value={n.entity_id}>
                        {n.canonical_name} ({n.entity_type})
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}

            {/* Evidence Selector Dropdown */}
            <div className="customModalBody" style={{ marginTop: 12, borderTop: "1px solid #eee", paddingTop: 12 }}>
              <label className="deskField">
                <span>Evidence Quote</span>
                <select 
                  value={selectedEvidenceId}
                  onChange={(e) => setSelectedEvidenceId(e.target.value)}
                  title={quotes.find(q => q.evidence_id === selectedEvidenceId)?.quote || "No quote selected"}
                >
                  <option value="">No Evidence (Do not create mention)</option>
                  {quotes.map(q => (
                    <option key={q.evidence_id} value={q.evidence_id} title={q.quote}>
                      {sourceTitle} - Page {q.page} ({q.evidence_id.split('_').pop().toUpperCase()}): {q.quote.length > 60 ? q.quote.substring(0, 60) + "..." : q.quote}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="customModalActions">
              <button className="quietButton light" onClick={() => setEntityModalOpen(false)}>Cancel</button>
              <button className="primaryButton" onClick={handleSaveEntityApproval}>Approve mention</button>
            </div>
          </div>
        </div>
      )}

      {/* Relationship Modal */}
      {relModalOpen && (
        <div className="customModalOverlay">
          <div className="customModal">
            <h3 className="customModalTitle">Create Relationship</h3>
            <div className="customModalBody">
              <CategorySelector
                label="Relation Type"
                value={newRel.relation_type || "spouse"}
                onChange={(val) => setNewRel({ ...newRel, relation_type: val })}
                types={relationTypes}
                setTypes={setRelationTypes}
                isEntity={false}
              />
              <label className="deskField">
                <span>Confidence</span>
                <select 
                  value={newRel.confidence} 
                  onChange={(e) => setNewRel({ ...newRel, confidence: e.target.value })}
                >
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </label>
              <label className="deskField">
                <span>Evidence Quote</span>
                <select 
                  value={newRel.evidence_id || ""} 
                  onChange={(e) => setNewRel({ ...newRel, evidence_id: e.target.value })}
                  title={quotes.find(q => q.evidence_id === newRel.evidence_id)?.quote || "No quote selected"}
                >
                  <option value="">Select a quote...</option>
                  {quotes.map(q => (
                    <option key={q.evidence_id} value={q.evidence_id} title={q.quote}>
                      {sourceTitle} - Page {q.page} ({q.evidence_id.split('_').pop().toUpperCase()}): {q.quote.length > 60 ? q.quote.substring(0, 60) + "..." : q.quote}
                    </option>
                  ))}
                </select>
              </label>
              <label className="deskField">
                <span>Note</span>
                <textarea 
                  value={newRel.note} 
                  onChange={(e) => setNewRel({ ...newRel, note: e.target.value })}
                />
              </label>
            </div>
            <div className="customModalActions">
              <button className="quietButton light" onClick={() => setRelModalOpen(false)}>Cancel</button>
              <button className="primaryButton" onClick={handleSaveRelationship}>Create Edge</button>
            </div>
          </div>
        </div>
      )}

      {/* Selected Node Inspector / Editor */}
      {selectedNodeEntity && (
        <div className="customModalOverlay">
          <div className="customModal">
            <h3 className="customModalTitle">Inspect / Edit Node Entity</h3>
            <div className="customModalBody">
              <label className="deskField">
                <span>Canonical Name</span>
                <input 
                  type="text" 
                  value={selectedNodeEntity.canonical_name || ""} 
                  onChange={(e) => setSelectedNodeEntity({ ...selectedNodeEntity, canonical_name: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Name (Original)</span>
                <input 
                  type="text" 
                  value={selectedNodeEntity.name_original || ""} 
                  onChange={(e) => setSelectedNodeEntity({ ...selectedNodeEntity, name_original: e.target.value })}
                />
              </label>
              <CategorySelector
                label="Type"
                value={selectedNodeEntity.entity_type || "person"}
                onChange={(val) => setSelectedNodeEntity({ ...selectedNodeEntity, entity_type: val })}
                types={entityTypes}
                setTypes={setEntityTypes}
                isEntity={true}
              />
              <label className="deskField">
                <span>Aliases (comma separated)</span>
                <input 
                  type="text" 
                  value={selectedNodeEntity.aliasesString || ""} 
                  onChange={(e) => setSelectedNodeEntity({ ...selectedNodeEntity, aliasesString: e.target.value })}
                />
              </label>
              <label className="deskField">
                <span>Notes</span>
                <textarea 
                  value={selectedNodeEntity.notes || ""} 
                  onChange={(e) => setSelectedNodeEntity({ ...selectedNodeEntity, notes: e.target.value })}
                />
              </label>
              <div className="deskField">
                <span>Linked Evidence Quotes</span>
                <div className="inspectorQuotesList" style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid #ccc', padding: 8, borderRadius: 4, background: '#f9f9f9', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {(() => {
                    const mentionsForNode = (artifact?.entity_mentions || []).filter(m => m.entity_id === selectedNodeEntity.entity_id);
                    if (mentionsForNode.length === 0) {
                      return <span style={{ color: '#666', fontStyle: 'italic' }}>No linked evidence quotes.</span>;
                    }
                    return mentionsForNode.map(mention => {
                      const matchingQuote = quotes.find(q => q.evidence_id === mention.evidence_id);
                      if (!matchingQuote) return null;
                      return (
                        <div key={mention.mention_id} style={{ fontSize: '0.9rem', borderBottom: '1px solid #eee', paddingBottom: 6 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', color: '#666', marginBottom: 2 }}>
                            <strong>{selectedSourceId === "project" ? `${matchingQuote.source_id} · ` : ""}Page {matchingQuote.page}</strong>
                            <div style={{ display: "flex", gap: "6px" }}>
                              <button
                                type="button"
                                onClick={() => handleLocateQuote(matchingQuote)}
                                style={{
                                  background: "#eef3f1",
                                  border: "1px solid #cbdad6",
                                  color: "#284f54",
                                  borderRadius: "4px",
                                  padding: "2px 6px",
                                  fontSize: "0.75rem",
                                  cursor: "pointer",
                                  display: "inline-flex",
                                  alignItems: "center"
                                }}
                              >
                                Locate Quote
                              </button>
                              {onJumpToReadingDesk && (
                                <button
                                  type="button"
                                  onClick={() => onJumpToReadingDesk(matchingQuote.source_id, matchingQuote.page)}
                                  style={{
                                    background: "#eef3f1",
                                    border: "1px solid #cbdad6",
                                    color: "#284f54",
                                    borderRadius: "4px",
                                    padding: "2px 6px",
                                    fontSize: "0.75rem",
                                    cursor: "pointer",
                                    display: "inline-flex",
                                    alignItems: "center"
                                  }}
                                >
                                  Locate in Reading Desk
                                </button>
                              )}
                            </div>
                          </div>
                          <div style={{ fontStyle: 'italic', color: '#333' }}>"{matchingQuote.quote}"</div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>
            </div>
            <div className="customModalActions">
              {!graphReadOnly && <button className="quietButton light deleteButton" onClick={handleDeleteNodeEntity}>Delete Node</button>}
              {!graphReadOnly && onMergeTrigger && (
                <button 
                  className="quietButton light" 
                  style={{ color: "var(--color-primary, #284f54)", borderColor: "var(--color-primary, #284f54)" }}
                  onClick={() => {
                    onMergeTrigger(selectedNodeEntity.entity_id);
                    setSelectedNodeEntity(null);
                  }}
                >
                  Merge...
                </button>
              )}
              <div style={{ flex: 1 }}></div>
              <button className="quietButton light" onClick={() => setSelectedNodeEntity(null)}>Cancel</button>
              {!graphReadOnly && <button className="primaryButton" onClick={handleUpdateNodeEntity}>Save Node</button>}
            </div>
          </div>
        </div>
      )}

      {/* Selected Edge Inspector / Editor */}
      {selectedEdgeRelation && (
        <div className="customModalOverlay">
          <div className="customModal">
            <h3 className="customModalTitle">Inspect Edge Relationship</h3>
            <div className="customModalBody">
              <label className="deskField">
                <span>Subject Entity</span>
                <input 
                  type="text" 
                  value={nodes.find(n => n.entity_id === selectedEdgeRelation.subject_entity_id)?.canonical_name || selectedEdgeRelation.subject_entity_id} 
                  disabled 
                />
              </label>
              <label className="deskField">
                <span>Object Entity</span>
                <input 
                  type="text" 
                  value={nodes.find(n => n.entity_id === selectedEdgeRelation.object_entity_id)?.canonical_name || selectedEdgeRelation.object_entity_id} 
                  disabled 
                />
              </label>
              
              <CategorySelector
                label="Relationship Type"
                value={selectedEdgeRelation.relation_type || ""}
                onChange={(val) => setSelectedEdgeRelation({ ...selectedEdgeRelation, relation_type: val })}
                types={relationTypes}
                setTypes={setRelationTypes}
                isEntity={false}
              />
              
              <label className="deskField">
                <span>Confidence</span>
                <select 
                  value={selectedEdgeRelation.confidence || "medium"}
                  onChange={(e) => setSelectedEdgeRelation({ ...selectedEdgeRelation, confidence: e.target.value })}
                >
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </label>
              <label className="deskField">
                <span>Notes</span>
                <textarea 
                  value={selectedEdgeRelation.note || ""} 
                  onChange={(e) => setSelectedEdgeRelation({ ...selectedEdgeRelation, note: e.target.value })}
                />
              </label>

              <label className="deskField">
                <span>Evidence Quote</span>
                <div style={{ padding: 8, border: '1px solid #ccc', borderRadius: 4, background: '#f9f9f9' }}>
                  {(() => {
                    const matchingQuote = quotes.find(q => q.evidence_id === selectedEdgeRelation.evidence_id);
                    if (!matchingQuote) {
                      return <span style={{ color: '#666', fontStyle: 'italic' }}>No linked evidence quote found ({selectedEdgeRelation.evidence_id}).</span>;
                    }
                     return (
                      <div style={{ fontSize: '0.9rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', color: '#666', marginBottom: 2 }}>
                          <strong>{selectedSourceId === "project" ? `${matchingQuote.source_id} · ` : ""}Page {matchingQuote.page}</strong>
                          <div style={{ display: "flex", gap: "6px" }}>
                            <button
                              type="button"
                              onClick={() => handleLocateQuote(matchingQuote)}
                              style={{
                                background: "#eef3f1",
                                border: "1px solid #cbdad6",
                                color: "#284f54",
                                borderRadius: "4px",
                                padding: "2px 6px",
                                fontSize: "0.75rem",
                                cursor: "pointer",
                                display: "inline-flex",
                                alignItems: "center"
                              }}
                            >
                              Locate Quote
                            </button>
                            {onJumpToReadingDesk && (
                              <button
                                type="button"
                                onClick={() => onJumpToReadingDesk(matchingQuote.source_id, matchingQuote.page)}
                                style={{
                                  background: "#eef3f1",
                                  border: "1px solid #cbdad6",
                                  color: "#284f54",
                                  borderRadius: "4px",
                                  padding: "2px 6px",
                                  fontSize: "0.75rem",
                                  cursor: "pointer",
                                  display: "inline-flex",
                                  alignItems: "center"
                                }}
                              >
                                Locate in Reading Desk
                              </button>
                            )}
                          </div>
                        </div>
                        <div style={{ fontStyle: 'italic', color: '#333' }}>"{matchingQuote.quote}"</div>
                      </div>
                     );
                  })()}
                </div>
              </label>
            </div>
            
            <div className="customModalActions">
              {!graphReadOnly && <button className="quietButton light deleteButton" onClick={handleDeleteEdgeRelation}>Delete Edge</button>}
              <div style={{ flex: 1 }}></div>
              <button className="quietButton light" onClick={() => setSelectedEdgeRelation(null)}>Cancel</button>
              {!graphReadOnly && <button className="primaryButton" onClick={handleUpdateEdgeRelation}>Save Edge</button>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CategorySelector({ label, value, onChange, types, setTypes, isEntity }) {
  const [isOpen, setIsOpen] = useState(false);
  const inputId = useMemo(() => `new_type_input_${Math.random().toString(36).substr(2, 9)}`, []);

  const handleAdd = () => {
    const input = document.getElementById(inputId) as HTMLInputElement | null;
    const val = input?.value.trim().toLowerCase();
    if (val && !types.includes(val)) {
      setTypes([...types, val]);
      input.value = "";
    }
  };

  return (
    <div style={{ marginBottom: 12 }}>
      <label className="deskField" style={{ marginBottom: 4 }}>
        <span>{label}</span>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <select 
            value={value || ""}
            onChange={(e) => onChange(e.target.value)}
            style={{ flex: 1 }}
          >
            {types.map(t => (
              <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
            ))}
          </select>
          <button 
            type="button" 
            className="quietButton light" 
            onClick={() => setIsOpen(!isOpen)}
            style={{ padding: "4px 8px", fontSize: "0.8rem", height: "auto" }}
          >
            Manage
          </button>
        </div>
      </label>
      {isOpen && (
        <div className="manageTypesBox" style={{ background: "var(--bg-surface-elevated, #f9f9f9)", padding: 10, borderRadius: 6, border: "1px solid var(--border-color)", marginTop: 6 }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <input 
              type="text" 
              id={inputId} 
              placeholder="Add new category..." 
              style={{ flex: 1, padding: "4px 8px", fontSize: 12, border: "1px solid var(--border-color)", borderRadius: 4, background: "var(--bg-surface, #fff)", color: "var(--text-primary)" }} 
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAdd();
                }
              }}
            />
            <button 
              type="button" 
              className="primaryButton" 
              style={{ padding: "4px 10px", fontSize: 12, height: "auto" }}
              onClick={handleAdd}
            >
              Add
            </button>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {types.map(t => (
              <span key={t} className="typeTag" style={{ background: "var(--bg-surface-elevated, #e2e8f0)", border: "1px solid var(--border-color)", padding: "2px 6px", borderRadius: 4, fontSize: 11, display: "flex", alignItems: "center", gap: 4, color: "var(--text-primary)" }}>
                {t}
                {(!isEntity || (t !== "person" && t !== "place" && t !== "organization")) && 
                 (isEntity || t !== "spouse") && (
                  <span 
                    style={{ cursor: "pointer", color: "#ef4444", fontWeight: "bold" }} 
                    onClick={() => setTypes(types.filter(x => x !== t))}
                  >
                    ×
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function MergeEntitiesModal({ isOpen, onClose, entities, onMerge, initialTargetId = "" }) {
  const [targetId, setTargetId] = useState(initialTargetId);
  const [selectedSourceIds, setSelectedSourceIds] = useState([]);

  useEffect(() => {
    if (isOpen) {
      setTargetId(initialTargetId);
      setSelectedSourceIds([]);
    }
  }, [isOpen, initialTargetId]);

  if (!isOpen) return null;

  // Filter out the target entity from candidate source entities
  const candidateSources = entities.filter(e => e.entity_id !== targetId);

  const handleCheckboxChange = (entityId, checked) => {
    if (checked) {
      setSelectedSourceIds([...selectedSourceIds, entityId]);
    } else {
      setSelectedSourceIds(selectedSourceIds.filter(id => id !== entityId));
    }
  };

  const handleSubmit = () => {
    if (!targetId) {
      alert("Please select a target entity.");
      return;
    }
    if (selectedSourceIds.length === 0) {
      alert("Please select at least one entity to merge.");
      return;
    }
    onMerge(targetId, selectedSourceIds);
  };

  return (
    <div className="customModalOverlay">
      <div className="customModal" style={{ maxWidth: 500 }}>
        <h3 className="customModalTitle">Merge Entities</h3>
        <div className="customModalBody">
          <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: 16 }}>
            Select the primary entity name. All other selected entities will be merged into it, and their names and aliases will become aliases of the primary entity. The merged entity will inherit all mentions, relationships, and attitude claims.
          </p>
          
          <label className="deskField">
            <span>Primary Entity (Surviving Node)</span>
            <select value={targetId} onChange={(e) => {
              setTargetId(e.target.value);
              setSelectedSourceIds([]);
            }}>
              <option value="">Select primary entity...</option>
              {entities.map(e => (
                <option key={e.entity_id} value={e.entity_id}>
                  {e.canonical_name} ({e.entity_type}) - {e.entity_id}
                </option>
              ))}
            </select>
          </label>

          {targetId && (
            <div className="deskField" style={{ marginTop: 12 }}>
              <span>Select Entities to Merge (Other Nodes to Combine)</span>
              <div style={{ maxHeight: 200, overflowY: "auto", border: "1px solid var(--border-color)", borderRadius: 4, padding: 8, background: "var(--bg-surface-elevated)" }}>
                {candidateSources.map(e => (
                  <label key={e.entity_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", cursor: "pointer", fontSize: "0.9rem" }}>
                    <input 
                      type="checkbox" 
                      checked={selectedSourceIds.includes(e.entity_id)}
                      onChange={(evt) => handleCheckboxChange(e.entity_id, evt.target.checked)}
                    />
                    <span>{e.canonical_name} ({e.entity_type}) - <small>{e.entity_id}</small></span>
                  </label>
                ))}
                {candidateSources.length === 0 && (
                  <span style={{ color: "var(--text-secondary)", fontStyle: "italic" }}>No other entities available to merge.</span>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="customModalActions">
          <button className="quietButton light" onClick={onClose}>Cancel</button>
          <button className="primaryButton" onClick={handleSubmit} disabled={!targetId || selectedSourceIds.length === 0}>Merge Nodes</button>
        </div>
      </div>
    </div>
  );
}


export default Workbench;
