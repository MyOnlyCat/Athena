interface Props {
  eyebrow: string;
  title: string;
  description: string;
}

export function FoundationPage({ eyebrow, title, description }: Props) {
  return (
    <div className="empty-page">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="muted">{description}</p>
    </div>
  );
}
