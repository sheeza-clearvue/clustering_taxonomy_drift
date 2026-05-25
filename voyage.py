import os
import numpy as np
import voyageai


def cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors @ vectors.T


def main():
    if not os.getenv("VOYAGE_API_KEY", "pa-gtqI7HTwnrGgOwkPKBqOI-Qgyz6B2Il9F4Jx79QhabG"):
        raise RuntimeError("VOYAGE_API_KEY is missing. Set it before running the script.")

    client = voyageai.Client()

    labels = [
        "agent insulted customer",
        "agent insulted by customer",
        "customer insulted agent",
        "agent was rude to customer",
        "customer was rude to agent",
        "broker insulted customer",
        "customer insulted broker",
    ]

    result = client.embed(
        labels,
        model="voyage-4",
        input_type="document",
        output_dimension=1024,
        output_dtype="float",
    )

    vectors = np.array(result.embeddings, dtype=np.float32)

    print("Embedding shape:", vectors.shape)
    print()

    sim = cosine_similarity_matrix(vectors)

    print("Cosine similarity matrix:")
    print(" " * 32 + " | ".join([str(i).rjust(5) for i in range(len(labels))]))

    for i, row in enumerate(sim):
        scores = " | ".join([f"{score:5.3f}" for score in row])
        print(f"{i}. {labels[i][:28].ljust(28)} {scores}")

    print()
    print("Label index:")
    for i, label in enumerate(labels):
        print(f"{i}: {label}")


if __name__ == "__main__":
    main()