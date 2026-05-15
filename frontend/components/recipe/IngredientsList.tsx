'use client';

import { useState } from 'react';
import styles from '../../app/recetas/pollo-al-ajillo-facil/recipe.module.css';
import { Check } from 'lucide-react';

interface Ingredient {
  name: string;
  amount: string;
  notes?: string;
}

interface IngredientsListProps {
  ingredients: Ingredient[];
}

export default function IngredientsList({ ingredients }: IngredientsListProps) {
  const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>({});

  const toggleItem = (index: number) => {
    setCheckedItems(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  return (
    <div className={styles.card}>
      <h2 className={styles.ingredientsTitle}>Ingredientes</h2>
      <ul className={styles.checklist}>
        {ingredients.map((item, index) => (
          <li 
            key={index} 
            className={`${styles.checkItem} ${checkedItems[index] ? styles.checked : ''}`}
            onClick={() => toggleItem(index)}
          >
            <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${checkedItems[index] ? 'bg-brand-fresa border-brand-fresa' : 'border-cream-dark'}`}>
              {checkedItems[index] && <Check size={14} className="text-white" />}
            </div>
            <p>
              <strong>{item.amount}</strong> {item.name}
              {item.notes && <span className="text-sm opacity-70 ml-2">({item.notes})</span>}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
