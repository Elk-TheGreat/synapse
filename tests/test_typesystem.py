import pytest

from synapse.typesystem import (
    ConversionError,
    DataType,
    PortSpec,
    TypeSpec,
    coerce_value,
    compatibility_error,
    infer_type,
    is_compatible,
    register_custom_type,
    type_label,
)


def test_infer_scalars():
    assert infer_type(True) is DataType.BOOLEAN
    assert infer_type(4) is DataType.INTEGER
    assert infer_type(4.5) is DataType.FLOAT
    assert infer_type("x") is DataType.STRING
    assert infer_type(b"x") is DataType.BYTES
    assert infer_type([1, 2]) is DataType.ARRAY
    assert infer_type({"a": 1}) is DataType.DICTIONARY
    assert infer_type(None) is DataType.ANY


def test_coerce_numbers_and_strings():
    assert coerce_value("42", DataType.INTEGER) == 42
    assert coerce_value("4.5", DataType.FLOAT) == 4.5
    assert coerce_value(3, DataType.FLOAT) == 3.0
    assert coerce_value(1, DataType.STRING) == "1"
    assert coerce_value("false", DataType.BOOLEAN) is False
    assert coerce_value(0, DataType.BOOLEAN) is False


def test_coerce_rejects_bad_values():
    try:
        coerce_value("abc", DataType.INTEGER)
    except ConversionError:
        pass
    else:
        raise AssertionError("expected ConversionError")
    try:
        coerce_value([1], DataType.STRING)
    except ConversionError:
        pass
    else:
        raise AssertionError("expected ConversionError")


def test_compatibility():
    assert is_compatible(DataType.INTEGER, DataType.FLOAT)
    assert is_compatible(DataType.INTEGER, DataType.ANY)
    assert not is_compatible(DataType.STRING, DataType.INTEGER)
    assert compatibility_error(DataType.STRING, DataType.INTEGER)
    assert is_compatible(DataType.BOOLEAN, DataType.INTEGER)
    assert is_compatible(DataType.ANY, DataType.OBJECT)
    assert not is_compatible(DataType.ARRAY, DataType.DICTIONARY)


def test_arrays_are_homogeneous():
    spec = TypeSpec(DataType.ARRAY, element=TypeSpec(DataType.INTEGER))
    assert coerce_value(["1", "2"], spec) == [1, 2]
    with pytest.raises(ConversionError):
        coerce_value(["x"], spec)


def test_custom_types():
    from synapse.typesystem.types import CustomType

    register_custom_type(
        CustomType(
            name="person",
            description="a person record",
            fields={"name": TypeSpec(DataType.STRING), "age": TypeSpec(DataType.INTEGER)},
        )
    )
    spec = TypeSpec(DataType.OBJECT, "person")
    assert is_compatible(spec, spec)
    assert not is_compatible(spec, DataType.INTEGER)
    assert coerce_value({"name": "Ada", "age": "36"}, spec) == {"name": "Ada", "age": "36"}
    with pytest.raises(ConversionError):
        coerce_value({"name": "Ada"}, spec)


def test_port_spec_serialisation():
    port = PortSpec("count", DataType.INTEGER, default=3, description="how many")
    restored = PortSpec.from_dict(port.to_dict())
    assert restored.name == "count" and restored.spec == port.spec
    assert restored.default == 3
