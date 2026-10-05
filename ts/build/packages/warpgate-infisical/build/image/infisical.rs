use std::{env, fs};

use reqwest::{Client, Url};
use serde::{Deserialize, Serialize};
use warpgate_common::{SshTargetInfisicalAuth, WarpgateError};
use zeroize::{Zeroize, Zeroizing};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LoginRequest<'a> {
    client_id: &'a str,
    client_secret: &'a str,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct LoginResponse {
    access_token: String,
}

#[derive(Deserialize)]
struct SecretEnvelope {
    secret: SecretValue,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SecretValue {
    secret_value: String,
}

fn base_url() -> Result<Url, WarpgateError> {
    let raw = env::var("INFISICAL_HOST_URL")
        .map_err(|_| anyhow::anyhow!("INFISICAL_HOST_URL is not configured"))?;
    Ok(Url::parse(raw.trim_end_matches('/'))?)
}

fn client_secret() -> Result<Zeroizing<String>, WarpgateError> {
    let path = env::var("INFISICAL_CLIENT_SECRET_FILE")
        .unwrap_or_else(|_| "/run/secrets/infisical-client-secret".into());
    let mut value = fs::read_to_string(path)?;
    while value.ends_with(['\r', '\n']) {
        value.pop();
    }
    if value.is_empty() {
        return Err(anyhow::anyhow!("Infisical machine identity client secret is empty").into());
    }
    Ok(Zeroizing::new(value))
}

pub async fn fetch_secret(
    auth: &SshTargetInfisicalAuth,
) -> Result<Zeroizing<String>, WarpgateError> {
    if auth.project_id.is_empty() || auth.environment.is_empty() || auth.secret_key.is_empty() {
        return Err(anyhow::anyhow!("incomplete Infisical SSH target reference").into());
    }

    let client_id = env::var("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID")
        .map_err(|_| anyhow::anyhow!("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID is not configured"))?;
    let client_secret = client_secret()?;
    let client = Client::builder().build()?;

    let mut login_url = base_url()?;
    login_url.set_path("/api/v1/auth/universal-auth/login");
    let login = client
        .post(login_url)
        .form(&LoginRequest {
            client_id: &client_id,
            client_secret: &client_secret,
        })
        .send()
        .await?
        .error_for_status()?
        .json::<LoginResponse>()
        .await?;
    let mut token = Zeroizing::new(login.access_token);

    let mut secret_url = base_url()?;
    {
        let mut segments = secret_url
            .path_segments_mut()
            .map_err(|_| anyhow::anyhow!("Infisical URL cannot be used as a base URL"))?;
        segments.clear();
        segments.extend(["api", "v4", "secrets", auth.secret_key.as_str()]);
    }
    secret_url
        .query_pairs_mut()
        .append_pair("projectId", &auth.project_id)
        .append_pair("environment", &auth.environment)
        .append_pair(
            "secretPath",
            if auth.secret_path.is_empty() { "/" } else { &auth.secret_path },
        );

    let response = client
        .get(secret_url)
        .bearer_auth(token.as_str())
        .send()
        .await?
        .error_for_status()?
        .json::<SecretEnvelope>()
        .await?;

    token.zeroize();
    Ok(Zeroizing::new(response.secret.secret_value))
}
