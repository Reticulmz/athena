#!/usr/bin/env python3
"""Prompt optimization の reference script。

Prompt template を test suite で評価し、単純な variation を比較して改善候補を
選ぶ最小構成の例を示す。

Constraints:
    LLM client は `complete(prompt: str) -> str` を持つ object を想定する。
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

TARGET_ACCURACY = 0.95
P95_PERCENTILE = 95


@dataclass
class TestCase:
    """Prompt 評価用 test case。

    Attributes:
        inputs: Prompt template に展開する values。
        expected_output: 期待する LLM output。
        metadata: 評価時に参照できる任意 metadata。
    """

    inputs: dict[str, Any]
    expected_output: str
    metadata: dict[str, Any] | None = None


class PromptOptimizer:
    """Prompt variation を評価して最良候補を選ぶ optimizer。"""

    def __init__(self, llm_client, test_suite: list[TestCase]):
        """PromptOptimizer を初期化する。

        Args:
            llm_client: `complete(prompt)` を実装する LLM client。
            test_suite: 評価に使う test cases。
        """
        self.client = llm_client
        self.test_suite = test_suite
        self.results_history = []
        self.executor = ThreadPoolExecutor()

    def shutdown(self):
        """ThreadPoolExecutor を停止する。

        Returns:
            None。
        """
        self.executor.shutdown(wait=True)

    def evaluate_prompt(
        self, prompt_template: str, test_cases: list[TestCase] | None = None
    ) -> dict[str, float]:
        """Prompt template を test cases に対して評価する。

        Args:
            prompt_template: `str.format` で inputs を展開する prompt template。
            test_cases: Optional test cases。未指定時は instance の test suite を使う。

        Returns:
            accuracy、latency、token count、success rate の集計 metrics。
        """
        if test_cases is None:
            test_cases = self.test_suite

        metrics = {"accuracy": [], "latency": [], "token_count": [], "success_rate": []}

        def process_test_case(test_case):
            start_time = time.time()

            # Render prompt with test case inputs
            prompt = prompt_template.format(**test_case.inputs)

            # Get LLM response
            response = self.client.complete(prompt)

            # Measure latency
            latency = time.time() - start_time

            # Calculate individual metrics
            token_count = len(prompt.split()) + len(response.split())
            success = 1 if response else 0
            accuracy = self.calculate_accuracy(response, test_case.expected_output)

            return {
                "latency": latency,
                "token_count": token_count,
                "success_rate": success,
                "accuracy": accuracy,
            }

        # Run test cases in parallel
        results = list(self.executor.map(process_test_case, test_cases))

        # Aggregate metrics
        for result in results:
            metrics["latency"].append(result["latency"])
            metrics["token_count"].append(result["token_count"])
            metrics["success_rate"].append(result["success_rate"])
            metrics["accuracy"].append(result["accuracy"])

        return {
            "avg_accuracy": _mean_or_zero(metrics["accuracy"]),
            "avg_latency": _mean_or_zero(metrics["latency"]),
            "p95_latency": _percentile(metrics["latency"], P95_PERCENTILE),
            "avg_tokens": _mean_or_zero(metrics["token_count"]),
            "success_rate": _mean_or_zero(metrics["success_rate"]),
        }

    def calculate_accuracy(self, response: str, expected: str) -> float:
        """Response と expected output の一致度を計算する。

        Args:
            response: LLM response。
            expected: 期待 output。

        Returns:
            0.0 から 1.0 の簡易 accuracy score。
        """
        # Simple exact match
        if response.strip().lower() == expected.strip().lower():
            return 1.0

        # Partial match using word overlap
        response_words = set(response.lower().split())
        expected_words = set(expected.lower().split())

        if not expected_words:
            return 0.0

        overlap = len(response_words & expected_words)
        return overlap / len(expected_words)

    def optimize(self, base_prompt: str, max_iterations: int = 5) -> dict[str, Any]:
        """Prompt を反復的に改善する。

        Args:
            base_prompt: 改善開始点の prompt template。
            max_iterations: 最大 iteration 数。

        Returns:
            best_prompt、best_score、history を含む dict。
        """
        current_prompt = base_prompt
        best_prompt = base_prompt
        best_score = 0
        current_metrics = None

        for iteration in range(max_iterations):
            print(f"\nIteration {iteration + 1}/{max_iterations}")

            # Evaluate current prompt
            # Avoid re-evaluating if previous iteration already produced metrics.
            metrics = current_metrics or self.evaluate_prompt(current_prompt)

            print(
                f"Accuracy: {metrics['avg_accuracy']:.2f}, Latency: {metrics['avg_latency']:.2f}s"
            )

            # Track results
            self.results_history.append(
                {"iteration": iteration, "prompt": current_prompt, "metrics": metrics}
            )

            # Update best if improved
            if metrics["avg_accuracy"] > best_score:
                best_score = metrics["avg_accuracy"]
                best_prompt = current_prompt

            # Stop if good enough
            if metrics["avg_accuracy"] > TARGET_ACCURACY:
                print("Achieved target accuracy!")
                break

            # Generate variations for next iteration
            variations = self.generate_variations(current_prompt, metrics)

            # Test variations and pick best
            best_variation = current_prompt
            best_variation_score = metrics["avg_accuracy"]
            best_variation_metrics = metrics

            for variation in variations:
                var_metrics = self.evaluate_prompt(variation)
                if var_metrics["avg_accuracy"] > best_variation_score:
                    best_variation_score = var_metrics["avg_accuracy"]
                    best_variation = variation
                    best_variation_metrics = var_metrics

            current_prompt = best_variation
            current_metrics = best_variation_metrics

        return {
            "best_prompt": best_prompt,
            "best_score": best_score,
            "history": self.results_history,
        }

    def generate_variations(self, prompt: str, _current_metrics: dict) -> list[str]:
        """評価する prompt variations を生成する。

        Args:
            prompt: 現在の prompt。
            _current_metrics: 現在 prompt の metrics。この例では参照しない。

        Returns:
            評価候補の prompt variations。
        """
        variations = []

        # Variation 1: Add explicit format instruction
        variations.append(prompt + "\n\nProvide your answer in a clear, concise format.")

        # Variation 2: Add step-by-step instruction
        variations.append("Let's solve this step by step.\n\n" + prompt)

        # Variation 3: Add verification step
        variations.append(prompt + "\n\nVerify your answer before responding.")

        # Variation 4: Make more concise
        concise = self.make_concise(prompt)
        if concise != prompt:
            variations.append(concise)

        # Variation 5: Add examples (if none present)
        if "example" not in prompt.lower():
            variations.append(self.add_examples(prompt))

        return variations[:3]  # Return top 3 variations

    def make_concise(self, prompt: str) -> str:
        """冗長な表現を置換して prompt を短くする。

        Args:
            prompt: 短縮対象の prompt。

        Returns:
            短縮後の prompt。
        """
        replacements = [
            ("in order to", "to"),
            ("due to the fact that", "because"),
            ("at this point in time", "now"),
            ("in the event that", "if"),
        ]

        result = prompt
        for old, new in replacements:
            result = result.replace(old, new)

        return result

    def add_examples(self, prompt: str) -> str:
        """Prompt に example section を追加する。

        Args:
            prompt: example を追加する prompt。

        Returns:
            Example section 付き prompt。
        """
        return f"""{prompt}

Example:
Input: Sample input
Output: Sample output
"""

    def compare_prompts(self, prompt_a: str, prompt_b: str) -> dict[str, Any]:
        """2つの prompt を A/B test する。

        Args:
            prompt_a: 比較対象 A。
            prompt_b: 比較対象 B。

        Returns:
            両 prompt の metrics、winner、improvement を含む dict。
        """
        print("Testing Prompt A...")
        metrics_a = self.evaluate_prompt(prompt_a)

        print("Testing Prompt B...")
        metrics_b = self.evaluate_prompt(prompt_b)

        return {
            "prompt_a_metrics": metrics_a,
            "prompt_b_metrics": metrics_b,
            "winner": "A" if metrics_a["avg_accuracy"] > metrics_b["avg_accuracy"] else "B",
            "improvement": abs(metrics_a["avg_accuracy"] - metrics_b["avg_accuracy"]),
        }

    def export_results(self, filename: str):
        """Optimization history を JSON file に出力する。

        Args:
            filename: 出力先 file path。

        Returns:
            None。
        """
        with Path(filename).open("w", encoding="utf-8") as f:
            json.dump(self.results_history, f, indent=2)


def _mean_or_zero(values: list[float]) -> float:
    """空 list を 0.0 として平均値を返す。

    Args:
        values: 集計対象の数値 list。

    Returns:
        平均値。空の場合は 0.0。
    """
    if not values:
        return 0.0
    return float(mean(values))


def _percentile(values: list[float], percentile: int) -> float:
    """線形補間で percentile 値を計算する。

    Args:
        values: 集計対象の数値 list。
        percentile: 0 から 100 の percentile。

    Returns:
        percentile に対応する値。空の場合は 0.0。
    """
    if not values:
        return 0.0

    sorted_values = sorted(values)
    position = (len(sorted_values) - 1) * percentile / 100
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    return lower_value + (upper_value - lower_value) * fraction


def main():
    """Reference script の example workflow を実行する。

    Returns:
        None。
    """
    # Example usage
    test_suite = [
        TestCase(inputs={"text": "This movie was amazing!"}, expected_output="Positive"),
        TestCase(inputs={"text": "Worst purchase ever."}, expected_output="Negative"),
        TestCase(inputs={"text": "It was okay, nothing special."}, expected_output="Neutral"),
    ]

    # Mock LLM client for demonstration
    class MockLLMClient:
        def complete(self, prompt):
            # Simulate LLM response
            if "amazing" in prompt:
                return "Positive"
            if "worst" in prompt.lower():
                return "Negative"
            return "Neutral"

    optimizer = PromptOptimizer(MockLLMClient(), test_suite)

    try:
        base_prompt = "Classify the sentiment of: {text}\nSentiment:"

        results = optimizer.optimize(base_prompt)

        print("\n" + "=" * 50)
        print("Optimization Complete!")
        print(f"Best Accuracy: {results['best_score']:.2f}")
        print(f"Best Prompt:\n{results['best_prompt']}")

        optimizer.export_results("optimization_results.json")
    finally:
        optimizer.shutdown()


if __name__ == "__main__":
    main()
