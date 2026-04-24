"""API contracts for ModelAdmin review-candidate service surface."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


CandidateLabel = Literal["invoice", "purchase-order", "goods-receipt-note"]


class CandidateLabelRequest(BaseModel):
    label: CandidateLabel


class CandidateApprovalRequest(BaseModel):
    pass


class CandidateRejectionRequest(BaseModel):
    pass


class ReviewCandidateItem(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    document_id: str
    status: str
    blob_path: str
    processed_blob_path: Optional[str] = None
    predicted_document_type: Optional[str] = None
    classification_confidence: Optional[float] = None
    compose_model_id: str
    has_low_confidence: bool
    trigger_reason: str
    low_confidence_fields: List[str] = Field(default_factory=list)
    low_confidence_field_count: Optional[int] = None
    source_channel: Optional[str] = None
    original_filename: Optional[str] = None
    operator_label: Optional[str] = None
    reviewed_at: Optional[str] = None
    approved_at: Optional[str] = None
    error_details: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ReviewCandidatesPagination(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int


class ReviewCandidatesFilters(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: Optional[str] = None
    document_type: Optional[str] = None
    trigger_reason: Optional[str] = None
    compose_model_id: Optional[str] = None
    source_channel: Optional[str] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    sort_by: str
    sort_order: str


class ListReviewCandidatesResponse(BaseModel):
    items: List[ReviewCandidateItem]
    pagination: ReviewCandidatesPagination
    filters: ReviewCandidatesFilters


class ReviewCandidateResponse(BaseModel):
    item: ReviewCandidateItem


class ReviewCandidateMutationResponse(BaseModel):
    success: bool
    item: ReviewCandidateItem
    changes: Dict[str, Any]


class TrainingDatasetCreateRequest(BaseModel):
    name: str
    created_by: str
    candidate_ids: List[str]
    parent_dataset_id: Optional[str] = None


class TrainingDatasetMarkReadyRequest(BaseModel):
    min_items_per_class: int = 5


class TrainingDatasetMembershipItemResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    candidate_id: str
    document_id: Optional[str] = None
    original_filename: Optional[str] = None
    operator_label: Optional[str] = None
    compose_model_id: str
    approved_at: Optional[str] = None


class RecheckFileResult(BaseModel):
    doc_type: str
    filename: str
    has_ocr: bool
    has_labels: bool
    has_schema_match: bool = True
    missing_field_keys: List[str] = Field(default_factory=list)
    unexpected_field_keys: List[str] = Field(default_factory=list)


class RecheckResponse(BaseModel):
    all_verified: bool
    new_status: str
    results: List[RecheckFileResult]


class TrainingDatasetItemResponse(BaseModel):
    id: str
    name: str
    status: str
    created_by: str
    label_verification_status: Optional[str] = None
    ready_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    membership_count: int


class TrainingDatasetDetailResponse(BaseModel):
    item: TrainingDatasetItemResponse
    membership: List[TrainingDatasetMembershipItemResponse]


class ListTrainingDatasetsResponse(BaseModel):
    items: List[TrainingDatasetItemResponse]
    pagination: ReviewCandidatesPagination


class TrainingDatasetMutationResponse(BaseModel):
    success: bool
    item: TrainingDatasetItemResponse


class RetrainJobItemResponse(BaseModel):
    id: str
    training_dataset_id: str
    status: str
    adi_operation_id: Optional[str] = None
    adi_model_id: Optional[str] = None
    error_message: Optional[str] = None
    submitted_at: Optional[str] = None
    updated_at: Optional[str] = None


class ListRetrainJobsResponse(BaseModel):
    items: List[RetrainJobItemResponse]


class RetrainJobMutationResponse(BaseModel):
    success: bool
    item: RetrainJobItemResponse


class ActiveModelConfigItemResponse(BaseModel):
    active_model_id: str
    activated_at: Optional[str] = None
    updated_at: Optional[str] = None


class ActiveModelConfigResponse(BaseModel):
    item: ActiveModelConfigItemResponse


class ActiveModelConfigMutationResponse(BaseModel):
    success: bool
    item: ActiveModelConfigItemResponse


class ComposeModelItemResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    model_kind: str
    version_number: int
    adi_created_at: Optional[str] = None
    classifier_model_id: Optional[str] = None
    extractor_models: List[str] = []
    is_available: bool
    is_active: bool


class ComposeModelListResponse(BaseModel):
    items: List[ComposeModelItemResponse]


class TrainingJobOperationItemResponse(BaseModel):
    id: str
    job_id: str
    operation_type: str
    doc_type: Optional[str] = None
    adi_operation_id: Optional[str] = None
    adi_model_id: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TrainingJobItemResponse(BaseModel):
    id: str
    dataset_version_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    operations: List[TrainingJobOperationItemResponse] = []


class TrainingJobMutationResponse(BaseModel):
    success: bool
    item: TrainingJobItemResponse


class ListTrainingJobsResponse(BaseModel):
    items: List[TrainingJobItemResponse]


class DatasetClassCountsResponse(BaseModel):
    dataset_id: str
    chain_ids: List[str]
    per_class_counts: Dict[str, int]


BootstrapExtractorType = Literal["invoice", "purchase-order", "goods-receipt-note"]


class BootstrapImportRequest(BaseModel):
    """Registers a single externally-created ADI compose model bundle into the DB.

    ``extractors`` is a mapping of model_type -> model_id, e.g.
    ``{"invoice": "invoice-extractor-v1", "purchase-order": "po-extractor-v1"}``.

    ``training_data`` is optional and specifies a local dataset to upload to blob storage
    before registering the models.
    """

    training_data: Optional[Dict[str, str]] = None
    compose_model_id: str
    classifier_model_id: str
    extractors: Dict[BootstrapExtractorType, str] = Field(min_length=1)
    activate: bool = True


class BootstrapImportValidationResponse(BaseModel):
    """Returned by POST /bootstrap/validate — merged contract + ADI check result."""

    success: bool
    compose_model_id: str
    classifier_model_id: str
    extractor_count: int
    activate: bool
    missing_model_ids: List[str] = Field(default_factory=list)


class BootstrapImportApplyResponse(BaseModel):
    success: bool
    compose_model_id: str
    classifier_model_id: str
    extractor_count: int
    activated: bool
