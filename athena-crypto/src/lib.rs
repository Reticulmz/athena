use pyo3::prelude::*;

#[pymodule]
fn athena_crypto(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(decrypt_score_payload, m)?)?;
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (encrypted, iv, osu_version=None))]
fn decrypt_score_payload(
    encrypted: &[u8],
    iv: &[u8],
    osu_version: Option<&str>,
) -> PyResult<(String, bool)> {
    use simple_rijndael::impls::RijndaelCbc;
    use simple_rijndael::paddings::ZeroPadding;

    let key = match osu_version {
        Some(ver) => format!("osu!-scoreburgr---------{}", ver),
        None => "h89f2-890h2h89b34g-h80g134n90133".to_string(),
    };

    let cipher: RijndaelCbc<ZeroPadding> = RijndaelCbc::new(key.as_bytes(), 32)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Cipher init failed: {:?}", e)))?;
    let decrypted = cipher.decrypt(iv, encrypted.to_vec())
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Decryption failed: {:?}", e)))?;

    let plaintext = String::from_utf8(decrypted)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid UTF-8: {}", e)))?;

    let checksum_valid = plaintext.ends_with("    ");

    Ok((plaintext, checksum_valid))
}
