export function SentimentBadge({ score }) {
  if (score === null || score === undefined) {
    return <span className="tag bg-gray-100 text-gray-500">—</span>;
  }
  if (score >= 0.2) {
    return (
      <span className="tag bg-green-100 text-green-700">
        +{score.toFixed(2)}
      </span>
    );
  }
  if (score >= -0.2) {
    return (
      <span className="tag bg-yellow-100 text-yellow-700">
        {score.toFixed(2)}
      </span>
    );
  }
  return (
    <span className="tag bg-red-100 text-red-700">
      {score.toFixed(2)}
    </span>
  );
}
