import pytest
from pydantic import HttpUrl

from pccontext.models.token_metadata_model import (
    AnnotatedSignature,
    TokenMetadata,
    TokenMetadataProperty,
)


@pytest.mark.parametrize(
    "signature, public_key",
    [
        ("valid_signature_1", "valid_public_key_1"),  # happy path
        ("valid_signature_2", "valid_public_key_2"),  # happy path
        ("", ""),  # edge case: empty strings
        ("a" * 1000, "b" * 1000),  # edge case: very long strings
    ],
    ids=[
        "happy_path_1",
        "happy_path_2",
        "edge_case_empty_strings",
        "edge_case_long_strings",
    ],
)
def test_annotated_signature_initialization(signature, public_key):

    # Act
    annotated_signature = AnnotatedSignature(signature=signature, public_key=public_key)

    # Assert
    assert annotated_signature.signature == signature
    assert annotated_signature.public_key == public_key


# Happy path tests with various realistic test values
@pytest.mark.parametrize(
    "value, sequence_number, signatures",
    [
        (
            123,
            1,
            [
                AnnotatedSignature(signature="valid_signature_1", public_key="valid_public_key_1"),
                AnnotatedSignature(signature="valid_signature_2", public_key="valid_public_key_2"),
            ],
        ),
        (
            "string_value",
            2,
            [AnnotatedSignature(signature="valid_signature_1", public_key="valid_public_key_1")],
        ),
        (
            b"bytes_value",
            3,
            [
                AnnotatedSignature(signature="valid_signature_1", public_key="valid_public_key_1"),
                AnnotatedSignature(signature="valid_signature_2", public_key="valid_public_key_2"),
            ],
        ),
        (
            HttpUrl("http://example.com"),
            4,
            [AnnotatedSignature(signature="valid_signature_1", public_key="valid_public_key_1")],
        ),
    ],
    ids=[
        "int_value",
        "str_value",
        "bytes_value",
        "http_url_value",
    ],
)
def test_token_metadata_property_happy_path(value, sequence_number, signatures):
    # Act
    token_metadata_property = TokenMetadataProperty(value=value, sequence_number=sequence_number, signatures=signatures)

    # Assert
    assert token_metadata_property.value == value
    assert token_metadata_property.sequence_number == sequence_number
    assert token_metadata_property.signatures == signatures


@pytest.mark.parametrize(
    "subject, policy, name, url, description, logo, ticker",
    [
        # Happy path tests
        (
            "subject1",
            TokenMetadataProperty(value="policy1", sequence_number=1, signatures=[]),
            TokenMetadataProperty(value="name1", sequence_number=2, signatures=[]),
            TokenMetadataProperty(value="http://example.com", sequence_number=3, signatures=[]),
            TokenMetadataProperty(value="description1", sequence_number=4, signatures=[]),
            TokenMetadataProperty(value="logo1", sequence_number=5, signatures=[]),
            TokenMetadataProperty(value="ticker1", sequence_number=6, signatures=[]),
        ),
        (
            "subject2",
            TokenMetadataProperty(value="policy2", sequence_number=1, signatures=[]),
            TokenMetadataProperty(value="name2", sequence_number=2, signatures=[]),
            TokenMetadataProperty(value="http://example.com", sequence_number=3, signatures=[]),
            TokenMetadataProperty(value="description2", sequence_number=4, signatures=[]),
            TokenMetadataProperty(value="logo2", sequence_number=5, signatures=[]),
            TokenMetadataProperty(value="ticker2", sequence_number=6, signatures=[]),
        ),
        (
            "",
            TokenMetadataProperty(value="", sequence_number=1, signatures=[]),
            TokenMetadataProperty(value="", sequence_number=2, signatures=[]),
            TokenMetadataProperty(value="", sequence_number=3, signatures=[]),
            TokenMetadataProperty(value="", sequence_number=4, signatures=[]),
            TokenMetadataProperty(value="", sequence_number=5, signatures=[]),
            TokenMetadataProperty(value="", sequence_number=6, signatures=[]),
        ),
    ],
    ids=[
        "happy_path_1",
        "happy_path_2",
        "edge_case_empty_strings",
    ],
)
def test_token_metadata(subject, policy, name, url, description, logo, ticker):
    # Arrange

    # Act
    token_metadata = TokenMetadata(
        subject=subject,
        policy=policy,
        name=name,
        url=url,
        description=description,
        logo=logo,
        ticker=ticker,
    )

    # Assert
    assert token_metadata.subject == subject
    assert token_metadata.policy == policy
    assert token_metadata.name == name
    assert token_metadata.url == url
    assert token_metadata.description == description
    assert token_metadata.logo == logo
    assert token_metadata.ticker == ticker
