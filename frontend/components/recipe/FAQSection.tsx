import styles from '../../app/recetas/pollo-al-ajillo-facil/recipe.module.css';

interface FAQ {
  question: string;
  answer: string;
}

interface FAQSectionProps {
  faqs: FAQ[];
}

export default function FAQSection({ faqs }: FAQSectionProps) {
  return (
    <section className={styles.faqSection}>
      <h2 className="font-serif text-4xl mb-4 text-brand-fresa-deep">Preguntas Frecuentes</h2>
      <p className="text-zinc-600 mb-8 max-w-2xl">Todo lo que necesitas saber para que tu pollo al ajillo salga perfecto a la primera.</p>
      <div className={styles.faqGrid}>
        {faqs.map((faq, index) => (
          <div key={index} className={styles.faqItem}>
            <h4 className="font-bold text-lg">{faq.question}</h4>
            <p className="text-zinc-700 leading-relaxed">{faq.answer}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
