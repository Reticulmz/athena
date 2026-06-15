use pyo3::prelude::*;
use simple_rijndael::impls::RijndaelCbc;
use simple_rijndael::paddings::ZeroPadding;

const RIJNDAEL_BLOCK_SIZE: usize = 32;

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
    if iv.len() != RIJNDAEL_BLOCK_SIZE {
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

    let cipher: RijndaelCbc<ZeroPadding> = RijndaelCbc::new(&key, RIJNDAEL_BLOCK_SIZE)
        .map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Cipher init failed: {:?}", e))
        })?;
    let decrypted = cipher.decrypt(iv, encrypted.to_vec()).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Decryption failed: {:?}", e))
    })?;
    let (plaintext_bytes, checksum_valid) = strip_pkcs7_padding(decrypted);

    let plaintext = String::from_utf8(plaintext_bytes)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid UTF-8: {}", e)))?;

    Ok((plaintext, checksum_valid))
}

fn strip_pkcs7_padding(mut plaintext: Vec<u8>) -> (Vec<u8>, bool) {
    let Some(&padding_size_byte) = plaintext.last() else {
        return (plaintext, false);
    };

    let padding_size = usize::from(padding_size_byte);
    if padding_size == 0 || padding_size > RIJNDAEL_BLOCK_SIZE || padding_size > plaintext.len() {
        return (plaintext, false);
    }

    let padding_start = plaintext.len() - padding_size;
    if !plaintext[padding_start..]
        .iter()
        .all(|&byte| byte == padding_size_byte)
    {
        return (plaintext, false);
    }

    plaintext.truncate(padding_start);
    (plaintext, true)
}

#[cfg(test)]
mod tests {
    use super::strip_pkcs7_padding;

    #[test]
    fn strips_valid_pkcs7_padding() {
        let (plaintext, valid) = strip_pkcs7_padding(b"score\x03\x03\x03".to_vec());

        assert!(valid);
        assert_eq!(plaintext, b"score");
    }

    #[test]
    fn preserves_plaintext_when_pkcs7_padding_is_invalid() {
        let input = b"score\x03\x03\x02".to_vec();

        let (plaintext, valid) = strip_pkcs7_padding(input.clone());

        assert!(!valid);
        assert_eq!(plaintext, input);
    }
}
