"use client";

import { useEffect, useState } from "react";
import AuthLoginForm from "@/components/AuthLoginForm";
import styles from "@/components/LandingPage.module.css";

const pains = [
  {
    title: "Всё держится на одном человеке",
    text: "Руководитель или прораб вручную собирает статус по объекту, потому что целостной картины нет.",
  },
  {
    title: "Есть ощущение контроля, но нет системы",
    text: "Пока объектов мало, кажется, что всё под контролем. Но как только растёт нагрузка, эта схема начинает ломаться.",
  },
  {
    title: "Сроки срываются из-за мелких несостыковок",
    text: "Материалы не приехали, бригада ждёт, следующий этап сдвинулся, клиенту снова нужно что-то объяснять.",
  },
  {
    title: "Excel уже не управляет стройкой",
    text: "Он фиксирует информацию, но не держит зависимости, последовательность работ, людей и реальные сроки.",
  },
  {
    title: "Команда живёт в чатах и голосовых",
    text: "Важное теряется, задачи размываются, ответственность не закрепляется.",
  },
  {
    title: "Не видно прямой связи между порядком и прибылью",
    text: "Хотя в стройке деньги почти всегда привязаны к срокам, простоям и раннему обнаружению проблем.",
  },
];

const features = [
  "Загрузка сметы или структуры работ",
  "Типизация этапов: ИЖС, квартиры, коммерция",
  "Диаграмма Ганта с зависимостями",
  "Контроль бригад, материалов и техники",
  "План / факт по каждому этапу",
  "Статусы, блокеры и зоны риска",
  "Ответственные по работам и участкам",
  "Единая картина по всем объектам",
];

const workflow = [
  {
    step: "01",
    title: "Загружаете смету или перечень работ",
    text: "Система принимает основу проекта и раскладывает её на этапы и задачи.",
  },
  {
    step: "02",
    title: "Работы приводятся к типам",
    text: "Демонтаж, инженерка, черновая отделка, чистовая отделка, фасад, кровля, снабжение и другие блоки.",
  },
  {
    step: "03",
    title: "Формируется план",
    text: "По срокам, зависимостям, ответственным и приоритетам по объекту.",
  },
  {
    step: "04",
    title: "Назначаются ресурсы",
    text: "Люди, бригады, материалы, техника, закупки и потребности на этап.",
  },
  {
    step: "05",
    title: "Команда ведёт факт",
    text: "Что выполнено, что в работе, что блокируется, что требует решения сегодня.",
  },
  {
    step: "06",
    title: "Руководитель видит отклонения",
    text: "Где отставание, чего не хватает, где риск по срокам и на чём теряются деньги.",
  },
];

const audiences = [
  {
    title: "ИЖС",
    text: "Для компаний, которые строят частные дома и хотят стандартизировать этапы, бригады и сроки.",
  },
  {
    title: "Ремонт квартир",
    text: "Для тех, кто ведёт несколько ремонтов параллельно и хочет видеть состояние каждого объекта без хаоса.",
  },
  {
    title: "Коммерческие помещения",
    text: "Для проектов, где критичны сроки запуска, подрядчики, согласования, поставки и координация работ.",
  },
];

const dailyControl = [
  "По каким объектам есть отставание",
  "Какие этапы должны стартовать, но не готовы",
  "Каких материалов или ресурсов не хватает",
  "Кто отвечает за конкретный участок",
  "Где план не совпадает с фактом",
  "Какие решения нужно принять сегодня",
];

const faq = [
  {
    q: "Это сложно? Я не айтишник",
    a: "Нет. Это не тяжёлая корпоративная система и не сложный планировщик ради планировщика. По сути это понятный план работ, где видно этапы, сроки, ответственных и факт выполнения.",
  },
  {
    q: "У нас сейчас завал. Нет времени на внедрение",
    a: "Обычно именно поэтому система и нужна. Сейчас время уже тратится — на звонки, переносы, поиск информации и ручной контроль. Нормальное внедрение убирает хаос, а не добавляет его.",
  },
  {
    q: "Мы и так справляемся. Зачем что-то менять",
    a: "Часто это означает, что всё вытягивается опытом руководителя и постоянным ручным контролем. Это работает до первого роста нагрузки. Вопрос в том, сможете ли вы так же работать при x2 объектах.",
  },
  {
    q: "Люди не будут этим пользоваться",
    a: "Если инструмент помогает в ежедневной работе, им начинают пользоваться. Когда через систему понятно, кто выходит, что делает и что блокирует этап, польза становится очевидной и для прораба, и для бригады.",
  },
  {
    q: "А где тут деньги? Я не вижу прямой выгоды",
    a: "В стройке деньги почти всегда связаны со сроками. Любой сдвиг — это простой, переносы, потеря маржи и нервный клиент. Если система помогает раньше замечать отклонения, она влияет на прибыль напрямую.",
  },
  {
    q: "Excel и блокнот быстрее",
    a: "Пока объектов мало и всё держится на одном человеке — возможно. Но когда начинаются параллельные процессы, несколько подрядчиков, поставки и зависимые этапы, Excel уже не управляет, а только фиксирует.",
  },
  {
    q: "Боюсь, что внедрим систему и станет только хуже",
    a: "Хуже становится, когда контроля нет, но кажется, что он есть. Система просто показывает реальную картину раньше, пока проблему ещё можно исправить спокойно.",
  },
  {
    q: "У нас своя специфика: ИЖС, квартиры, коммерция — всё разное",
    a: "Детали разные, но логика стройки одна и та же: подготовка, инженерка, основные работы, отделка, сдача. Система даёт каркас, на который накладывается ваша специфика.",
  },
  {
    q: "Придётся всё переделывать и перестраивать процессы?",
    a: "Нет. Нормальный путь — взять один объект, собрать его в системе, увидеть разницу и потом использовать этот подход как шаблон.",
  },
  {
    q: "Уже пробовали программы. Не зашло",
    a: "Скепсис нормальный. Но главный вопрос не в том, пробовали ли вы софт, а даёт ли текущая система предсказуемый результат по срокам, загрузке и контролю.",
  },
  {
    q: "Это должен решать я или прораб?",
    a: "Если вы отвечаете за результат, сроки и деньги компании — это ваша задача тоже. Сроки — это не только операционка, это репутация и прибыль.",
  },
  {
    q: "Ещё одно приложение? У нас и так уже перегруз",
    a: "У большинства компаний уже есть набор инструментов: звонки, чаты, голосовые, Excel и память руководителя. Вопрос не в том, есть ли у вас система. Вопрос в том, насколько она дорогая, нервная и нестабильная.",
  },
  {
    q: "Я и так всё держу в голове",
    a: "Это может работать на маленьком масштабе. Но рост почти всегда ломает систему в голове. Чем больше объектов, людей и поставок, тем выше цена позднего решения.",
  },
  {
    q: "Пока не горит. Можно отложить",
    a: "В стройке это часто означает только одно: проблема ещё не стала видимой. Система нужна именно для того, чтобы видеть её раньше, а не когда уже приходится объясняться с клиентом.",
  },
];

const resultItems = [
  "Меньше ручного контроля",
  "Быстрее видно, где проблема",
  "Проще вести несколько объектов",
  "Меньше потерь информации в чатах",
  "Прозрачнее ответственность команды",
  "Выше предсказуемость сроков и бюджета",
];

const previewStats = [
  { label: "Этапов", value: "24" },
  { label: "В риске", value: "3" },
  { label: "Готовность", value: "68%" },
];

const previewTimeline = [
  { name: "Демонтаж", progress: "84%", status: "Завершён" },
  { name: "Инженерка", progress: "67%", status: "В работе" },
  { name: "Перегородки", progress: "52%", status: "Есть риск" },
  { name: "Чистовая отделка", progress: "24%", status: "Ожидает" },
];

const heroHighlights = [
  "Разберётесь быстро",
  "Без перестройки процессов",
  "План, факт и блокеры в одном месте",
  "Меньше простоев и ручного контроля",
];

export default function LandingPage() {
  const [isLoginOpen, setIsLoginOpen] = useState(false);

  useEffect(() => {
    if (!isLoginOpen) {
      document.body.style.overflow = "";
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsLoginOpen(false);
      }
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);

    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isLoginOpen]);

  return (
    <>
      <main className={styles.page}>
        <section className={styles.section}>
          <div className={`${styles.container} ${styles.hero}`}>
            <div className={styles.topBar}>
              <div className={styles.brand}>СтройКонтроль</div>
              <button
                type="button"
                className={styles.cabinetButton}
                onClick={() => setIsLoginOpen(true)}
              >
                Личный кабинет
              </button>
            </div>

            <div className={styles.heroGrid}>
              <div>
                <div className={styles.eyebrow}>
                  Для ИЖС, ремонта квартир и коммерческих помещений
                </div>

                <h1 className={styles.heroTitle}>
                  Контроль стройки в одной системе — от сметы до факта выполнения
                </h1>

                <p className={styles.heroText}>
                  Свяжите смету, этапы работ, ресурсы, сроки, ответственных и фактическое
                  выполнение в одном понятном рабочем контуре. Без хаоса в Excel, чатах и
                  ручном контроле.
                </p>

                <div className={styles.heroActions}>
                  <a href="#contact" className={styles.primaryAction}>
                    Запросить демо
                  </a>
                  <a href="#how-it-works" className={styles.secondaryAction}>
                    Посмотреть как это работает
                  </a>
                </div>

                <div className={styles.heroHighlights}>
                  {heroHighlights.map((item) => (
                    <div key={item} className={styles.pillCard}>
                      {item}
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.previewShell}>
                <div className={styles.previewCard}>
                  <div className={styles.previewHeader}>
                    <div>
                      <p className={styles.previewLabel}>Объект</p>
                      <h3 className={styles.previewHeading}>Ремонт коммерческого помещения</h3>
                    </div>
                    <span className={styles.statusBadge}>Под контролем</span>
                  </div>

                  <div className={styles.statsGrid}>
                    {previewStats.map((stat) => (
                      <div key={stat.label} className={styles.statCard}>
                        <p className={styles.previewLabel}>{stat.label}</p>
                        <p className={styles.statValue}>{stat.value}</p>
                      </div>
                    ))}
                  </div>

                  <div className={styles.timelineCard}>
                    <div className={styles.timelineHeader}>
                      <span>Диаграмма этапов</span>
                      <span>План / факт</span>
                    </div>

                    <div className={styles.timelineList}>
                      {previewTimeline.map((row) => (
                        <div key={row.name}>
                          <div className={styles.previewRow}>
                            <span className={styles.timelineName}>{row.name}</span>
                            <span className={styles.timelineStatus}>{row.status}</span>
                          </div>
                          <div className={styles.progressTrack}>
                            <div
                              className={styles.progressFill}
                              style={{ width: row.progress }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className={styles.infoGrid}>
                    <div className={styles.infoCard}>
                      <p className={styles.previewLabel}>Блокер</p>
                      <p className={styles.cardText}>
                        Поставка чистовых материалов не закрыта. Риск сдвига следующего этапа
                        на 2 дня.
                      </p>
                    </div>
                    <div className={styles.infoCard}>
                      <p className={styles.previewLabel}>Ответственный</p>
                      <p className={styles.cardText}>
                        Прораб, снабжение и подрядчик по электрике — видно, кто должен снять
                        проблему.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.sectionIntro}>
              <p className={styles.sectionTag}>Проблема рынка</p>
              <h2 className={styles.sectionTitle}>Даже небольшая стройка быстро превращается в хаос</h2>
              <p className={styles.sectionText}>
                Когда объектов становится больше одного, управление начинает распадаться: смета
                в одном файле, сроки в голове, задачи в чатах, закупки в звонках, а реальный
                статус знает только тот, кто сейчас на объекте.
              </p>
            </div>

            <div className={styles.cardGrid}>
              {pains.map((pain) => (
                <div key={pain.title} className={styles.panelCard}>
                  <h3 className={styles.cardTitle}>{pain.title}</h3>
                  <p className={styles.cardText}>{pain.text}</p>
                </div>
              ))}
            </div>

            <div className={styles.quoteCard}>
              <p className={styles.quoteText}>
                Проблема не в том, что люди плохо работают. Проблема в том, что процесс не
                собран в одну систему.
              </p>
            </div>
          </div>
        </section>

        <section className={`${styles.section} ${styles.sectionMuted}`}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.twoColGrid}>
              <div>
                <p className={styles.sectionTag}>Решение</p>
                <h2 className={styles.sectionTitle}>
                  Вместо хаоса в чатах и таблицах — единая система управления объектом
                </h2>
                <p className={styles.sectionText}>
                  Вы загружаете смету или структуру работ, а дальше система помогает собрать
                  объект в понятную рабочую модель:
                </p>
                <div className={styles.featureRibbon}>
                  смета → типы работ → ресурсы → сроки → ответственные → факт → отклонения
                </div>
                <p className={styles.smallText}>
                  Это не тяжёлая корпоративная система и не ещё один MS Project. Это понятный
                  рабочий инструмент для малого подрядчика: чтобы видеть, что происходит на
                  объекте, что тормозит работу и где теряются деньги.
                </p>
              </div>

              <div className={styles.splitGrid}>
                {features.map((feature) => (
                  <div key={feature} className={styles.panelCard}>
                    {feature}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="how-it-works" className={styles.section}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.sectionIntro}>
              <p className={styles.sectionTag}>Как это работает</p>
              <h2 className={styles.sectionTitle}>
                Планирование, ресурсы и контроль — в одном процессе
              </h2>
            </div>

            <div className={styles.cardGrid}>
              {workflow.map((item) => (
                <div key={item.step} className={styles.panelCard}>
                  <div className={styles.stepNumber}>{item.step}</div>
                  <h3 className={styles.cardTitle}>{item.title}</h3>
                  <p className={styles.cardText}>{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className={`${styles.section} ${styles.sectionMuted}`}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.twoColGrid}>
              <div>
                <p className={styles.sectionTag}>Каждый день в системе</p>
                <h2 className={styles.sectionTitle}>
                  Руководитель видит, что происходит на объекте без ручного сбора информации
                </h2>
                <p className={styles.sectionText}>
                  Не нужно держать всё в голове, ждать вечерних звонков и собирать картину по
                  кускам. Критичные отклонения, зависшие этапы и проблемные зоны видны раньше.
                </p>
              </div>

              <div className={styles.splitGrid}>
                {dailyControl.map((item) => (
                  <div key={item} className={styles.panelCard}>
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.sectionIntro}>
              <p className={styles.sectionTag}>Для кого</p>
              <h2 className={styles.sectionTitle}>
                Подходит тем, кто уже вырос из таблиц, но не хочет внедрять тяжёлую
                корпоративную систему
              </h2>
            </div>

            <div className={styles.threeColGrid}>
              {audiences.map((item) => (
                <div key={item.title} className={styles.panelCard}>
                  <h3 className={styles.cardTitle}>{item.title}</h3>
                  <p className={styles.cardText}>{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className={`${styles.section} ${styles.sectionMuted}`}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.threeColGrid}>
              <div className={styles.exampleCard}>
                <p className={styles.sectionTag}>Почему не Excel</p>
                <h3 className={styles.cardTitle}>Excel хранит данные, но не управляет стройкой</h3>
                <p className={styles.cardText}>
                  Пока объектов мало и всё держится на одном человеке, таблицы кажутся удобными.
                  Но когда появляются параллельные процессы, поставки и зависимые этапы, Excel
                  уже не управляет — он только фиксирует.
                </p>
              </div>

              <div className={styles.exampleCard}>
                <p className={styles.sectionTag}>Почему не чаты</p>
                <h3 className={styles.cardTitle}>Чаты удобны для общения, но не для контроля</h3>
                <p className={styles.cardText}>
                  Важное теряется, задачи размываются, а статусы меняются только в голове
                  руководителя. Это не система контроля, а постоянная реакция на то, что уже
                  произошло.
                </p>
              </div>

              <div className={styles.exampleCard}>
                <p className={styles.sectionTag}>Почему не task manager</p>
                <h3 className={styles.cardTitle}>Стройка — это не список задач</h3>
                <p className={styles.cardText}>
                  Это этапы, сроки, ресурсы, поставки, факт выполнения и ответственность.
                  Обычные таск-менеджеры этого не понимают. Они не знают логику объекта.
                </p>
              </div>
            </div>

            <div className={styles.quoteCard}>
              <p className={styles.quoteText}>
                Сейчас у многих уже есть “система”: звонки, чаты, таблицы и память руководителя.
                Просто это самая дорогая и нестабильная система из возможных.
              </p>
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.sectionIntro}>
              <p className={styles.sectionTag}>Пример</p>
              <h2 className={styles.sectionTitle}>Как выглядит работа по объекту в системе</h2>
            </div>

            <div className={styles.twoColGrid} style={{ marginTop: 44 }}>
              <div className={styles.exampleCard}>
                <p className={styles.previewLabel}>Объект</p>
                <h3 className={styles.cardTitle}>Ремонт коммерческого помещения 180 м²</h3>
                <p className={styles.cardText}>
                  Смета загружена в систему. Работы разбиты на этапы: демонтаж, инженерка,
                  перегородки, отделка, электрика, финиш. На каждом этапе есть сроки,
                  зависимости, ответственный, материалы и факт выполнения.
                </p>
              </div>

              <div className={styles.exampleCard}>
                <p className={styles.previewLabel}>Что видно руководителю утром</p>
                <ul className={styles.bulletList}>
                  <li>электрика отстаёт на 2 дня</li>
                  <li>перегородки не стартуют без поставки</li>
                  <li>закупка по чистовым материалам не закрыта</li>
                  <li>нужно решение по подрядчику на потолок</li>
                  <li>видно, кто должен снять проблему</li>
                </ul>
                <p className={styles.smallText}>
                  Это и есть управление стройкой, а не постоянный ручной сбор информации.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className={`${styles.section} ${styles.sectionMuted}`}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.twoColGrid}>
              <div>
                <p className={styles.sectionTag}>Результат</p>
                <h2 className={styles.sectionTitle}>Что меняется после внедрения</h2>
                <p className={styles.sectionText}>
                  Вы перестаёте управлять стройкой через память, звонки и постоянные
                  разбирательства. Появляется единая система, в которой каждый объект проходит
                  понятный путь: от сметы до завершения.
                </p>
              </div>

              <div className={styles.splitGrid}>
                {resultItems.map((item) => (
                  <div key={item} className={styles.panelCard}>
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <div className={`${styles.container} ${styles.sectionBlock}`}>
            <div className={styles.sectionIntro}>
              <p className={styles.sectionTag}>Часто задаваемые вопросы</p>
              <h2 className={styles.sectionTitle}>
                Возражения, которые возникают почти у каждого подрядчика
              </h2>
            </div>

            <div className={styles.faqList}>
              {faq.map((item) => (
                <details key={item.q} className={styles.faqItem}>
                  <summary className={styles.faqSummary}>{item.q}</summary>
                  <p className={styles.faqAnswer}>{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section id="contact" className={styles.finalCta}>
          <div className={styles.container}>
            <div className={styles.finalCard}>
              <p className={styles.sectionTag}>Финальный шаг</p>
              <h2 className={styles.sectionTitle}>
                Хватит управлять стройкой через Excel и переписки
              </h2>
              <p className={styles.ctaText}>
                Покажем, как ваш объект будет выглядеть в системе: со сметой, этапами, сроками,
                ответственными, ресурсами и контролем факта выполнения.
              </p>

              <div className={styles.ctaActions}>
                <a href="mailto:hello@example.com" className={styles.primaryAction}>
                  Запросить демо
                </a>
                <a href="tel:+70000000000" className={styles.secondaryAction}>
                  Связаться сейчас
                </a>
              </div>

              <p className={styles.ctaNote}>
                Разберётесь быстро. Без тяжёлого внедрения. Первый объект можно собрать как
                пилотный сценарий.
              </p>
            </div>
          </div>
        </section>
      </main>

      {isLoginOpen && (
        <div className={styles.modalOverlay} onClick={() => setIsLoginOpen(false)}>
          <div className={styles.modalDialog} onClick={(event) => event.stopPropagation()}>
            <button
              type="button"
              className={styles.modalClose}
              onClick={() => setIsLoginOpen(false)}
              aria-label="Закрыть форму авторизации"
            >
              ×
            </button>
            <AuthLoginForm variant="modal" onSuccess={() => setIsLoginOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
