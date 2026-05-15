import Image from 'next/image';
import styles from '../../app/recetas/pollo-al-ajillo-facil/recipe.module.css';
import { Info, Lightbulb } from 'lucide-react';

interface Step {
  title: string;
  description: string;
  tip?: string;
  important?: string;
  image?: string;
}

interface StepByStepProps {
  steps: Step[];
}

export default function StepByStep({ steps }: StepByStepProps) {
  return (
    <div className={styles.steps}>
      <h2 className="font-serif text-4xl mb-12 text-brand-fresa-deep">Preparación Paso a Paso</h2>
      {steps.map((step, index) => (
        <div key={index} className={styles.step}>
          <div className={styles.stepNumber}>{index + 1}</div>
          <div className={styles.stepContent}>
            <h3>{step.title}</h3>
            
            {step.image && (
              <div className="relative aspect-video mb-6 rounded-lg overflow-hidden border border-gray-100 shadow-sm">
                <Image 
                  src={step.image} 
                  alt={`${step.title} - Paso ${index + 1}`}
                  fill
                  sizes="(max-width: 1024px) 100vw, 800px"
                  className="object-cover"
                />
              </div>
            )}

            <p className="text-lg leading-relaxed text-zinc-700 mb-6">{step.description}</p>
            
            {step.tip && (
              <div className={`${styles.alertBox} bg-gold-light/10 border-gold-accent`}>
                <div className="flex items-center gap-2 mb-2 text-gold-accent font-bold uppercase tracking-wider text-xs">
                  <Lightbulb size={16} />
                  <span>Consejo del Chef</span>
                </div>
                <p className="italic text-zinc-800">{step.tip}</p>
              </div>
            )}

            {step.important && (
              <div className={`${styles.alertBox} bg-brand-fresa/5 border-brand-fresa`}>
                <div className="flex items-center gap-2 mb-2 text-brand-fresa font-bold uppercase tracking-wider text-xs">
                  <Info size={16} />
                  <span>¡Importante!</span>
                </div>
                <p className="text-brand-fresa-deep">{step.important}</p>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
