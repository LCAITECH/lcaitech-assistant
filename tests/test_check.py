from app.check import diagnose


def d(err, provider="vertex"):
    return diagnose(err, provider, "gemini-3.1-flash-lite", "global")


def test_diagnoses():
    assert "gcloud services enable aiplatform.googleapis.com" in d("403 PERMISSION_DENIED SERVICE_DISABLED Vertex AI API has not been used in project")
    assert "roles/aiplatform.user" in d("403 PERMISSION_DENIED Permission 'aiplatform.endpoints.predict' denied")
    assert "--scopes cloud-platform" in d("403 ACCESS_TOKEN_SCOPE_INSUFFICIENT Request had insufficient authentication scopes")
    assert "VERTEX_LOCATION=global" in d("404 NOT_FOUND Publisher Model was not found")
    assert "ADC" in d("DefaultCredentialsError: Your default credentials were not found")
    assert "--api-key" in d("400 API key not valid", provider="apikey")
