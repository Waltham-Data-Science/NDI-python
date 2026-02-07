"""
NDI Python Integration Demo

This demonstrates how ndi.Document (metadata layer) integrates with
ndi_compress (data storage layer) for a complete neuroscience data workflow.

Architecture:
- ndi.Document: stores metadata, file references, dependencies
- ndicompress: handles binary data compression/decompression
- Together: complete data management system

This is the workflow the cofounder is building toward!
"""

import numpy as np
import os
import tempfile

# Our NDI core (Phase 2 implementation)
from ndi import Document, Query, Ido
from ndi.common import timestamp

# Cofounder's compression library
try:
    import ndicompress
    HAS_COMPRESS = True
except ImportError:
    HAS_COMPRESS = False
    print("Note: ndicompress not installed. Install with: pip install ndicompress")


def demo_full_workflow():
    """
    Demonstrate the complete NDI workflow:
    1. Record ephys data (simulated)
    2. Compress it with ndicompress
    3. Create ndi.Document with metadata
    4. Link compressed file to document
    5. Query to find the document
    6. Retrieve and decompress the data
    """

    print("=" * 60)
    print("NDI Python Integration Demo")
    print("=" * 60)

    # === Step 1: Simulate recording ephys data ===
    print("\n[1] Simulating ephys recording...")

    num_samples = 30000  # 1 second at 30kHz
    num_channels = 4
    sample_rate = 30000

    # Simulate neural data: noise + spikes
    t = np.linspace(0, 1, num_samples)
    data = np.random.randn(num_samples, num_channels) * 50  # noise

    # Add some "spikes"
    for ch in range(num_channels):
        spike_times = np.random.choice(num_samples, size=20, replace=False)
        for st in spike_times:
            if st + 30 < num_samples:
                data[st:st+30, ch] += np.sin(np.linspace(0, np.pi, 30)) * 500

    data = data.astype(np.int16)  # Convert to int16 for ephys
    print(f"   Data shape: {data.shape}")
    print(f"   Data type: {data.dtype}")
    print(f"   Sample rate: {sample_rate} Hz")

    # === Step 2: Compress with ndicompress ===
    if HAS_COMPRESS:
        print("\n[2] Compressing data with ndicompress...")

        with tempfile.TemporaryDirectory() as tmpdir:
            filename_base = os.path.join(tmpdir, "ephys_recording")

            ratio, _, _, _ = ndicompress.compress_ephys(data, filename_base)
            compressed_file = filename_base + ".nbf.tgz"

            original_size = data.nbytes
            compressed_size = os.path.getsize(compressed_file)

            print(f"   Original size: {original_size:,} bytes")
            print(f"   Compressed size: {compressed_size:,} bytes")
            print(f"   Compression ratio: {ratio:.3f}")

            # === Step 3: Create ndi.Document with metadata ===
            print("\n[3] Creating ndi.Document with metadata...")

            # In real usage, we'd load from JSON schema
            # For demo, we create a simple document structure
            doc_props = {
                'base': {
                    'id': Ido().id,
                    'datestamp': timestamp(),
                    'name': 'ephys_recording_001',
                    'session_id': ''
                },
                'document_class': {
                    'class_name': 'ndi_document_ephys',
                    'superclasses': []
                },
                'ephys': {
                    'num_channels': num_channels,
                    'sample_rate': sample_rate,
                    'num_samples': num_samples,
                    'duration_seconds': num_samples / sample_rate,
                    'data_type': 'int16',
                    'compression': 'ndi_compress_ephys'
                },
                'files': {
                    'file_list': ['ephys_data.nbf_#'],
                    'file_info': []
                }
            }

            doc = Document(doc_props)

            # === Step 4: Link compressed file to document ===
            print("\n[4] Linking compressed file to document...")

            doc = doc.add_file(
                name='ephys_data.nbf_1',
                location=compressed_file,
                ingest=True
            )

            print(f"   Document ID: {doc.id}")
            print(f"   Document class: {doc.doc_class()}")
            print(f"   Files attached: {doc.current_file_list()}")

            # === Step 5: Query demonstration ===
            print("\n[5] Query demonstration...")

            # These queries would work with ndi.database
            q1 = Query('ephys.num_channels') == 4
            q2 = Query('ephys.sample_rate') > 20000
            q3 = Query('base.name').contains('ephys')

            # Combined query
            q_combined = q1 & q2 & q3

            print(f"   Query 1: {q1.to_searchstructure()}")
            print(f"   Query 2: {q2.to_searchstructure()}")
            print(f"   Query 3: {q3.to_searchstructure()}")

            # === Step 6: Retrieve and decompress ===
            print("\n[6] Retrieving and decompressing data...")

            data_recovered, _ = ndicompress.expand_ephys(compressed_file)

            print(f"   Recovered shape: {data_recovered.shape}")
            print(f"   Recovered dtype: {data_recovered.dtype}")

            # Verify data integrity
            max_diff = np.max(np.abs(data.astype(np.float64) - data_recovered))
            print(f"   Max difference from original: {max_diff}")

            if max_diff < 1e-6:
                print("   ✓ Data integrity verified!")

    else:
        print("\n[2-6] Skipped (ndicompress not installed)")
        print("   To see full demo, install: pip install ndicompress")

        # Still show document creation without compression
        print("\n[3] Creating ndi.Document (without compression)...")

        doc = Document('base')
        doc = doc.set_session_id('demo_session')
        doc = doc.setproperties(**{'base.name': 'ephys_demo'})

        print(f"   Document ID: {doc.id}")
        print(f"   Session ID: {doc.session_id}")

    # === Summary ===
    print("\n" + "=" * 60)
    print("INTEGRATION SUMMARY")
    print("=" * 60)
    print("""
    Our ndi.Document provides:
    ├── Unique IDs (ndi.Ido)
    ├── Metadata storage (JSON-based)
    ├── File attachment (add_file)
    ├── Dependencies tracking
    └── Query support (ndi.Query)

    Cofounder's ndicompress provides:
    ├── Efficient binary compression
    ├── Multiple data types (ephys, digital, time, events)
    └── .nbf.tgz format

    Together they form a complete data management system:

    [Raw Data] → [ndicompress] → [.nbf.tgz]
                                     ↓
                            [ndi.Document.add_file()]
                                     ↓
                             [ndi.database]
                                     ↓
                             [ndi.Query.search()]
    """)

    print("=" * 60)
    print("Demo complete!")
    print("=" * 60)


def demo_document_features():
    """Show off ndi.Document features that complement ndicompress."""

    print("\n" + "=" * 60)
    print("ndi.Document Feature Demo")
    print("=" * 60)

    # Create a document
    doc = Document('base')
    print(f"\n1. Created document with ID: {doc.id}")

    # Set session
    doc = doc.set_session_id('session_abc123')
    print(f"2. Set session ID: {doc.session_id}")

    # Bulk property setting (useful for ephys metadata)
    doc = doc.setproperties(**{
        'base.name': 'neural_recording',
    })
    print(f"3. Set name via setproperties")

    # Document equality (by ID)
    doc2 = Document(doc.document_properties)
    print(f"4. Document equality: doc == doc2 → {doc == doc2}")

    # Static methods for working with document arrays
    docs = [
        Document('base'),
        Document('base'),
        Document('base'),
    ]

    newest, idx, ts = Document.find_newest(docs)
    print(f"5. find_newest() found document at index {idx}")

    found, idx = Document.find_doc_by_id(docs, docs[1].id)
    print(f"6. find_doc_by_id() found document at index {idx}")

    # JSON export
    json_str = doc.to_json()
    print(f"7. to_json() produces {len(json_str)} characters")

    print("\nAll features work and are ready to integrate with ndicompress!")


if __name__ == '__main__':
    demo_full_workflow()
    demo_document_features()
