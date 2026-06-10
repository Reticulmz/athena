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

    if iv.len() != 32 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "IV must be 32 bytes, got {}",
            iv.len()
        )));
    }

    if encrypted.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Encrypted data cannot be empty"
        ));
    }

    let mut key = [0u8; 32];

    match osu_version {
        Some(ver) => {
            let prefix = b"osu!-scoreburgr---------";
            let ver_bytes = ver.as_bytes();
            let prefix_len = prefix.len();
            let ver_len = ver_bytes.len().min(32 - prefix_len);

            key[..prefix_len].copy_from_slice(prefix);
            key[prefix_len..prefix_len + ver_len].copy_from_slice(&ver_bytes[..ver_len]);
        }
        None => {
            key.copy_from_slice(b"h89f2-890h2h89b34g-h80g134n90133");
        }
    }

    let cipher: RijndaelCbc<ZeroPadding> = RijndaelCbc::new(&key, 32)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Cipher init failed: {:?}", e)))?;
    let decrypted = cipher.decrypt(iv, encrypted.to_vec())
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Decryption failed: {:?}", e)))?;

    let plaintext = String::from_utf8(decrypted)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid UTF-8: {}", e)))?;

    let checksum_valid = plaintext.ends_with("    ");

    Ok((plaintext, checksum_valid))
}
