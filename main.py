import streamlit as st
import os
import io
from pathlib import Path

# الاستيرادات الأساسية لـ LlamaIndex
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, load_index_from_storage
from llama_index.readers.web import SimpleWebPageReader

# استيرادات Multi-modal RAG و Gemini
from llama_index.multi_modal_llms.google import GeminiMultiModal

from llama_index.google.genai import Gemini 
from PIL import Image

# استيراد حزمة جوجل لتوليد الصور
from google import genai 

# استيراد مكتبات التنزيل
from docx import Document
from pptx import Presentation
from pptx.util import Inches 

# ---------------------------------
# 1. الإعدادات الأساسية
# ---------------------------------

# **هام:** ضع مفتاحك في Secrets (GEMINI_API_KEY)
# os.environ["GEMINI_API_KEY"] = "أدخل_مفتاح_API_الخاص_بك_هنا" 

INDEX_STORAGE_DIR = "storage"
PDF_DIR = "./" 
IMAGE_GENERATION_MODEL = 'imagen-3.0-generate-002' 

MEDICAL_URLS = [
    "https://pubmed.ncbi.nlm.nih.gov/", 
    "https://www.who.int/ar", 
    "https://www.cdc.gov/",
    "https://www.mayoclinic.org/",
    "https://www.medscape.com/",
    "https://www.hopkinsmedicine.org/",
]

SYSTEM_PROMPT = (
    "أنت مساعد طبي ذكي متخصص في الإجابة على استفسارات طلاب الطب. "
    "يجب عليك تحليل النص والصورة المرفقة (إن وجدت) واستخدامها مع المراجع المسترجعة للإجابة. "
    "الإجابة يجب أن تكون باللغة العربية، مع الحفاظ على المصطلحات الطبية الأساسية (الأمراض، الأدوية، المصطلحات التشريحية) باللغة الإنجليزية/اللاتينية داخل الأقواس. "
    "عند طلب الجداول أو المقارنات أو الشروحات المعقدة، يجب أن تُنظَّم الإجابة في شكل نص مُهيكل (Markdown) واضح وموجز. "
    "قم بإنشاء أسئلة تدريبية وتلخيصات و Mnemonic Devices (تحشيشات) عند طلبها."
)

# ---------------------------------
# 2. بناء/تحميل الفهرس المتعدد الأنماط
# ---------------------------------

@st.cache_resource
def setup_rag_engine():
    
    if "GEMINI_API_KEY" not in os.environ and not Path(INDEX_STORAGE_DIR).exists():
        st.error("❌ المفتاح السري لـ Gemini مفقود! يرجى إضافته في Secrets.")
        return None

    try:
        llm_multi = GeminiMultiModal(model="gemini-2.5-flash")
        llm_text = Gemini(model="gemini-2.5-flash")
    except Exception as e:
        st.error(f"❌ فشل تهيئة نموذج Gemini: {e}")
        return None

    if Path(INDEX_STORAGE_DIR).exists():
        st.info("🔄 جاري تحميل قاعدة المعرفة المتعددة الأنماط الموجودة مسبقًا...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_STORAGE_DIR)
        index = load_index_from_storage(storage_context, llm=llm_text)
        
    else:
        st.warning("⏳ جاري بناء قاعدة المعرفة المتعددة الأنماط (قد يستغرق وقتًا طويلاً)...")
        
        try:
            pdf_documents = SimpleDirectoryReader(input_dir=PDF_DIR, required_exts=[".pdf", ".jpg", ".png"]).load_data()
            url_documents = SimpleWebPageReader(input_urls=MEDICAL_URLS).load_data()
            documents = pdf_documents + url_documents
            st.info(f"تم تحميل {len(documents)} مستند (نصي وبصري). جاري الفهرسة...")

            index = VectorStoreIndex.from_documents(
                documents,
                llm=llm_multi,
            )
            index.storage_context.persist(persist_dir=INDEX_STORAGE_DIR)
            st.success("✅ تم بناء قاعدة المعرفة المتعددة الأنماط وحفظها بنجاح!")
            
        except Exception as e:
            st.error(f"❌ خطأ حرج في بناء الفهرس: {e}")
            return None

    query_engine = index.as_query_engine(
        llm=llm_text,
        system_prompt=SYSTEM_PROMPT,
        streaming=True
    )
    return query_engine

# ---------------------------------
# 3. دوال توليد الوسائط والتنزيل
# ---------------------------------

@st.cache_resource
def get_gemini_client():
    return genai.Client()

def generate_image(prompt: str, is_animation=False):
    """تستخدم نموذج Imagen لإنشاء صورة ثابتة (جرافيك) بناءً على الوصف."""
    client = get_gemini_client()
    
    full_prompt = (
        f"Detailed medical diagram, high-quality colorful graphic design, "
        f"featuring arrows and explanatory labels showing the {prompt}"
    )
    
    st.info(f"🎨 جاري توليد جرافيك توضيحي لـ: {prompt}")

    try:
        if is_animation:
            st.warning("توليد الفيديو/الصور المتحركة معقد في Streamlit. سيتم توليد صورة ثابتة بدلاً من ذلك.")
            
        result = client.models.generate_images(
            model=IMAGE_GENERATION_MODEL,
            prompt=full_prompt,
            config=dict(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="16:9"
            )
        )
        
        if result.generated_images:
            image_data = result.generated_images[0].image.image_bytes
            return image_data, None
        else:
            return None, "لم يتمكن النموذج من توليد صورة بناءً على الوصف."

    except Exception as e:
        return None, f"خطأ في توليد الصورة: {e}"

def convert_text_to_docx(text_content):
    """تحول النص إلى ملف Word (DOCX)."""
    document = Document()
    document.add_paragraph(text_content)
    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def convert_text_to_pptx(text_content):
    """تحول النص إلى عرض تقديمي (PPTX) بتقسيم بسيط."""
    prs = Presentation()
    
    # تقسيم النص إلى شرائح (بافتراض أن كل سطرين يمثلان شريحة جديدة)
    paragraphs = text_content.split('\n\n') 
    
    for i, p in enumerate(paragraphs):
        if not p.strip(): continue # تخطي الأسطر الفارغة
            
        # استخدام تخطيط العنوان والمحتوى
        slide_layout = prs.slide_layouts[1] 
        slide = prs.slides.add_slide(slide_layout)
        
        # العنوان هو أول 50 حرفًا
        title = slide.shapes.title
        title.text = f"شريحة {i+1}: " + p.split('\n')[0][:50] + "..."
        
        # المحتوى هو باقي النص
        body = slide.placeholders[1]
        tf = body.text_frame
        tf.text = p

    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# ---------------------------------
# 4. واجهة Streamlit (التطبيق الرئيسي)
# ---------------------------------

st.set_page_config(page_title="مساعدك الطبي (RAG+Vision)", layout="wide")
st.title("👁️ مساعدك الطبي البصري (RAG+Vision)")
st.caption("يحلل ملفاتك وصورك المرفوعة للإجابة، ويدعم التنزيل المتعدد.")

query_engine = setup_rag_engine()

def handle_image_generation(content, is_animation=False):
    image_prompt = content[:200]
    image_bytes, error = generate_image(image_prompt, is_animation=is_animation)

    if image_bytes:
        st.image(image_bytes, caption=f"صورة توضيحية تم توليدها لـ: {image_prompt}...")
        
        st.download_button(
            label="⬇️ تنزيل الصورة كـ JPG",
            data=image_bytes,
            file_name="medical_graphic.jpg",
            mime="image/jpeg",
            key=f"download_img_{hash(content)}"
        )
    else:
        st.error(f"فشل التوليد: {error}")


if query_engine:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # عرض الرسائل السابقة
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # أزرار التوليد والتنزيل لرد المساعد
            if message["role"] == "assistant":
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    if st.button("🖼️ توليد جرافيك", key=f"img_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=False)

                with col2:
                    docx_file = convert_text_to_docx(message["content"])
                    st.download_button(
                        label="📄 تنزيل كـ Word",
                        data=docx_file,
                        file_name="summary.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"download_docx_{hash(message['content'])}" 
                    )
                    
                with col3:
                    pptx_file = convert_text_to_pptx(message["content"])
                    st.download_button(
                        label="📊 تنزيل كـ PPTX",
                        data=pptx_file,
                        file_name="presentation.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        key=f"download_pptx_{hash(message['content'])}" 
                    )
                
                with col4:
                    st.download_button(
                        label="📜 تنزيل كـ TXT",
                        data=message["content"],
                        file_name="summary.txt",
                        mime="text/plain",
                        key=f"download_txt_{hash(message['content'])}" 
                    )

    # >>> منطقة تحميل الصورة والسؤال
    uploaded_file = st.file_uploader("🖼️ ارفع صورة طبية للسؤال عنها (اختياري)", type=["png", "jpg", "jpeg"])

    if prompt := st.chat_input("اطرح سؤالاً طبياً، ويمكنك إرفاق صورة..."):
        
        user_message = {"role": "user", "content": prompt}
        text_and_image_input = prompt
        image_to_query = None

        if uploaded_file:
            image = Image.open(uploaded_file)
            st.image(image, caption="الصورة المرفوعة", width=200)
            
            image_to_query = [image] 
            text_and_image_input = f"حلل الصورة المرفوعة معتمداً على مراجعك، ثم أجب عن السؤال: {prompt}"

        st.session_state.messages.append(user_message)
        with st.chat_message("user"):
            st.markdown(text_and_image_input)

        with st.chat_message("assistant"):
            response = query_engine.query(text_and_image_input, images=image_to_query) 
            
            st.write_stream(response.response_gen)
            st.session_state.messages.append({"role": "assistant", "content": response.response})
    "عند طلب الجداول أو المقارنات أو الشروحات المعقدة، يجب أن تُنظَّم الإجابة في شكل نص مُهيكل (Markdown) واضح وموجز."
# ---------------------------------
# 2. بناء/تحميل الفهرس المتعدد الأنماط
# ---------------------------------

@st.cache_resource
def setup_rag_engine():
    
    if "GEMINI_API_KEY" not in os.environ and not Path(INDEX_STORAGE_DIR).exists():
        st.error("❌ المفتاح السري لـ Gemini مفقود! يرجى إضافته في Secrets.")
        return None

    try:
        # LLM Multi-modal لقراءة وفهم النصوص والصور في الفهرس
        llm_multi = GeminiMultiModal(model="gemini-2.5-flash")
        # LLM النصي لمحرك الاستعلام النهائي
        llm_text = Gemini(model="gemini-2.5-flash")
        
    except Exception as e:
        st.error(f"❌ فشل تهيئة نموذج Gemini: {e}")
        return None

    if Path(INDEX_STORAGE_DIR).exists():
        st.info("🔄 جاري تحميل قاعدة المعرفة المتعددة الأنماط الموجودة مسبقًا...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_STORAGE_DIR)
        index = load_index_from_storage(storage_context, llm=llm_text)
        
    else:
        st.warning("⏳ جاري بناء قاعدة المعرفة المتعددة الأنماط (تأكد من وجود صور JPG/PNG وملفات PDF)...")
        
        try:
            # الآن تقرأ النصوص من PDF والصور من JPG/PNG
            pdf_documents = SimpleDirectoryReader(input_dir=PDF_DIR, required_exts=[".pdf", ".jpg", ".png"]).load_data()
            url_documents = SimpleWebPageReader(input_urls=MEDICAL_URLS).load_data()
            documents = pdf_documents + url_documents
            st.info(f"تم تحميل {len(documents)} مستند (نصي وبصري). جاري الفهرسة...")

            index = VectorStoreIndex.from_documents(
                documents,
                llm=llm_multi, # استخدام نموذج الأنماط المتعددة للفهرسة
            )
            index.storage_context.persist(persist_dir=INDEX_STORAGE_DIR)
            st.success("✅ تم بناء قاعدة المعرفة المتعددة الأنماط وحفظها بنجاح!")
            
        except Exception as e:
            st.error(f"❌ خطأ حرج في بناء الفهرس: {e}")
            return None

    query_engine = index.as_query_engine(
        llm=llm_text,
        system_prompt=SYSTEM_PROMPT,
        streaming=True
    )
    return query_engine

# ---------------------------------
# 3. دوال توليد الوسائط
# ---------------------------------

@st.cache_resource
def get_gemini_client():
    return genai.Client()

def generate_image(prompt: str, is_animation=False):
    """
    تستخدم نموذج Imagen لإنشاء صورة ثابتة (جرافيك) بناءً على الوصف.
    """
    client = get_gemini_client()
    
    # تحسين المطالبة لإنشاء صورة طبية احترافية
    full_prompt = (
        f"Detailed medical diagram, high-quality colorful graphic design, "
        f"featuring arrows and explanatory labels showing the {prompt}"
    )
    
    st.info(f"🎨 جاري توليد جرافيك توضيحي لـ: {prompt}")

    try:
        if is_animation:
            st.warning("توليد الفيديو/الصور المتحركة معقد في Streamlit. سيتم توليد صورة ثابتة بدلاً من ذلك.")
            
        result = client.models.generate_images(
            model=IMAGE_GENERATION_MODEL,
            prompt=full_prompt,
            config=dict(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="16:9"
            )
        )
        
        if result.generated_images:
            image_data = result.generated_images[0].image.image_bytes
            return image_data, None
        else:
            return None, "لم يتمكن النموذج من توليد صورة بناءً على الوصف."

    except Exception as e:
        if "API_KEY_INVALID" in str(e):
            return None, "خطأ: مفتاح Gemini API غير صالح أو غير مهيأ لخدمة Imagen."
        return None, f"خطأ في توليد الصورة: {e}"


# ---------------------------------
# 4. واجهة Streamlit (التطبيق الرئيسي)
# ---------------------------------

st.set_page_config(page_title="مساعدك الطبي (RAG+Vision)", layout="centered")
st.title("👁️ مساعدك الطبي البصري (RAG+Vision)")
st.caption("يحلل ملفاتك وصورك المرفوعة للإجابة.")

query_engine = setup_rag_engine()

def handle_image_generation(content, is_animation=False):
    # نستخدم جزء من الإجابة لتوليد مطالبة للصورة
    image_prompt = content[:200]
    
    image_bytes, error = generate_image(image_prompt, is_animation=is_animation)

    if image_bytes:
        st.image(image_bytes, caption=f"صورة توضيحية تم توليدها لـ: {image_prompt}...")
    else:
        st.error(f"فشل التوليد: {error}")


if query_engine:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # عرض الرسائل السابقة
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # إضافة أزرار التوليد بعد كل رد من المساعد
            if message["role"] == "assistant":
                col1, col2 = st.columns(2)
                
                # الزر 1: توليد صورة توضيحية (Graphic Design)
                with col1:
                    if st.button("🖼️ توليد جرافيك توضيحي", key=f"img_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=False)

                # الزر 2: توليد صورة متحركة (كبديل للفيديو)
                with col2:
                    if st.button("🎬 توليد صورة متحركة/فيديو", key=f"gif_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=True)


    # >>> منطقة تحميل الصورة والسؤال
    uploaded_file = st.file_uploader("🖼️ ارفع صورة طبية للسؤال عنها (اختياري)", type=["png", "jpg", "jpeg"])

    if prompt := st.chat_input("اطرح سؤالاً طبياً، ويمكنك إرفاق صورة..."):
        
        user_message = {"role": "user", "content": prompt}
        
        text_and_image_input = prompt
        image_to_query = None

        if uploaded_file:
            image = Image.open(uploaded_file)
            st.image(image, caption="الصورة المرفوعة", width=200)
            
            # تجهيز كائن الصورة ليتم تمريره إلى محرك الاستعلام
            image_to_query = [image] 

            # تعديل نص المطالبة ليتضمن التعليمات الخاصة بالصورة
            text_and_image_input = f"حلل الصورة المرفوعة معتمداً على مراجعك، ثم أجب عن السؤال: {prompt}"

        st.session_state.messages.append(user_message)
        with st.chat_message("user"):
            st.markdown(text_and_image_input)

        with st.chat_message("assistant"):
            # استدعاء محرك الاستعلام وتمرير الصورة المرفوعة (إن وجدت)
            response = query_engine.query(text_and_image_input, images=image_to_query) 
            
            st.write_stream(response.response_gen)
            st.session_state.messages.append({"role": "assistant", "content": response.response})
    "يجب عليك تحليل النص والصورة المرفقة (إن وجدت) واستخدامها مع المراجع المسترجعة للإجابة. "
    "الإجابة يجب أن تكون باللغة العربية، مع الحفاظ على المصطلحات الطبية الأساسية بالإنجليزية/اللاتينية. "
    "عند طلب الجداول أو المقارنات أو الشروحات المعقدة، يجب أن تُنظَّم الإجابة في شكل نص مُهيكل (Markdown) واضح وموجز."
# ---------------------------------
# 2. بناء/تحميل الفهرس المتعدد الأنماط
# ---------------------------------

@st.cache_resource
def setup_rag_engine():
    
    if "GEMINI_API_KEY" not in os.environ and not Path(INDEX_STORAGE_DIR).exists():
        st.error("❌ المفتاح السري لـ Gemini مفقود! يرجى إضافته في Secrets.")
        return None

    try:
        # LLM Multi-modal لقراءة وفهم النصوص والصور في الفهرس
        llm_multi = GeminiMultiModal(model="gemini-2.5-flash")
        # LLM النصي لمحرك الاستعلام النهائي
        llm_text = Gemini(model="gemini-2.5-flash")
        
    except Exception as e:
        st.error(f"❌ فشل تهيئة نموذج Gemini: {e}")
        return None

    if Path(INDEX_STORAGE_DIR).exists():
        st.info("🔄 جاري تحميل قاعدة المعرفة المتعددة الأنماط الموجودة مسبقًا...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_STORAGE_DIR)
        index = load_index_from_storage(storage_context, llm=llm_text)
        
    else:
        st.warning("⏳ جاري بناء قاعدة المعرفة المتعددة الأنماط (تأكد من وجود صور JPG/PNG وملفات PDF)...")
        
        try:
            # الآن تقرأ النصوص من PDF والصور من JPG/PNG
            pdf_documents = SimpleDirectoryReader(input_dir=PDF_DIR, required_exts=[".pdf", ".jpg", ".png"]).load_data()
            url_documents = SimpleWebPageReader(input_urls=MEDICAL_URLS).load_data()
            documents = pdf_documents + url_documents
            st.info(f"تم تحميل {len(documents)} مستند (نصي وبصري). جاري الفهرسة...")

            index = VectorStoreIndex.from_documents(
                documents,
                llm=llm_multi, # استخدام نموذج الأنماط المتعددة للفهرسة
            )
            index.storage_context.persist(persist_dir=INDEX_STORAGE_DIR)
            st.success("✅ تم بناء قاعدة المعرفة المتعددة الأنماط وحفظها بنجاح!")
            
        except Exception as e:
            st.error(f"❌ خطأ حرج في بناء الفهرس: {e}")
            return None

    query_engine = index.as_query_engine(
        llm=llm_text,
        system_prompt=SYSTEM_PROMPT,
        streaming=True
    )
    return query_engine

# ---------------------------------
# 3. دوال توليد الوسائط
# ---------------------------------

@st.cache_resource
def get_gemini_client():
    return genai.Client()

def generate_image(prompt: str, is_animation=False):
    """
    تستخدم نموذج Imagen لإنشاء صورة ثابتة (جرافيك) بناءً على الوصف.
    """
    client = get_gemini_client()
    
    # تحسين المطالبة لإنشاء صورة طبية احترافية
    full_prompt = (
        f"Detailed medical diagram, high-quality colorful graphic design, "
        f"featuring arrows and explanatory labels showing the {prompt}"
    )
    
    st.info(f"🎨 جاري توليد جرافيك توضيحي لـ: {prompt}")

    try:
        if is_animation:
            st.warning("توليد الفيديو/الصور المتحركة معقد في Streamlit. سيتم توليد صورة ثابتة بدلاً من ذلك.")
            
        result = client.models.generate_images(
            model=IMAGE_GENERATION_MODEL,
            prompt=full_prompt,
            config=dict(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="16:9"
            )
        )
        
        if result.generated_images:
            image_data = result.generated_images[0].image.image_bytes
            return image_data, None
        else:
            return None, "لم يتمكن النموذج من توليد صورة بناءً على الوصف."

    except Exception as e:
        if "API_KEY_INVALID" in str(e):
            return None, "خطأ: مفتاح Gemini API غير صالح أو غير مهيأ لخدمة Imagen."
        return None, f"خطأ في توليد الصورة: {e}"


# ---------------------------------
# 4. واجهة Streamlit (التطبيق الرئيسي)
# ---------------------------------

st.set_page_config(page_title="مساعدك الطبي (RAG+Vision)", layout="centered")
st.title("👁️ مساعدك الطبي البصري (RAG+Vision)")
st.caption("يحلل ملفاتك وصورك المرفوعة للإجابة.")

query_engine = setup_rag_engine()

def handle_image_generation(content, is_animation=False):
    # نستخدم جزء من الإجابة لتوليد مطالبة للصورة
    image_prompt = content[:200]
    
    image_bytes, error = generate_image(image_prompt, is_animation=is_animation)

    if image_bytes:
        st.image(image_bytes, caption=f"صورة توضيحية تم توليدها لـ: {image_prompt}...")
    else:
        st.error(f"فشل التوليد: {error}")


if query_engine:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # عرض الرسائل السابقة
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # إضافة أزرار التوليد بعد كل رد من المساعد
            if message["role"] == "assistant":
                col1, col2 = st.columns(2)
                
                # الزر 1: توليد صورة توضيحية (Graphic Design)
                with col1:
                    if st.button("🖼️ توليد جرافيك توضيحي", key=f"img_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=False)

                # الزر 2: توليد صورة متحركة (كبديل للفيديو)
                with col2:
                    if st.button("🎬 توليد صورة متحركة/فيديو", key=f"gif_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=True)


    # >>> منطقة تحميل الصورة والسؤال
    uploaded_file = st.file_uploader("🖼️ ارفع صورة طبية للسؤال عنها (اختياري)", type=["png", "jpg", "jpeg"])

    if prompt := st.chat_input("اطرح سؤالاً طبياً، ويمكنك إرفاق صورة..."):
        
        user_message = {"role": "user", "content": prompt}
        
        text_and_image_input = prompt
        image_to_query = None

        if uploaded_file:
            image = Image.open(uploaded_file)
            st.image(image, caption="الصورة المرفوعة", width=200)
            
            # تجهيز كائن الصورة ليتم تمريره إلى محرك الاستعلام
            image_to_query = [image] 

            # تعديل نص المطالبة ليتضمن التعليمات الخاصة بالصورة
            text_and_image_input = f"حلل الصورة المرفوعة معتمداً على مراجعك، ثم أجب عن السؤال: {prompt}"

        st.session_state.messages.append(user_message)
        with st.chat_message("user"):
            st.markdown(text_and_image_input)

        with st.chat_message("assistant"):
            # استدعاء محرك الاستعلام وتمرير الصورة المرفوعة (إن وجدت)
            response = query_engine.query(text_and_image_input, images=image_to_query) 
            
            st.write_stream(response.response_gen)
            st.session_state.messages.append({"role": "assistant", "content": response.response})
INDEX_STORAGE_DIR = "storage"
PDF_DIR = "./" 
IMAGE_GENERATION_MODEL = 'imagen-3.0-generate-002' # نموذج توليد الصور

MEDICAL_URLS = [
    "https://pubmed.ncbi.nlm.nih.gov/", 
    "https://www.who.int/ar", 
    "https://www.cdc.gov/",
    "https://www.mayoclinic.org/",
    "https://www.medscape.com/",
    "https://www.hopkinsmedicine.org/",
]

SYSTEM_PROMPT = (
    "أنت مساعد طبي ذكي متخصص في الإجابة على استفسارات طلاب الطب. "
    "الإجابة يجب أن تكون باللغة العربية، مع الحفاظ على المصطلحات الطبية الأساسية (الأمراض، الأدوية، المصطلحات التشريحية) باللغة الإنجليزية/اللاتينية داخل الأقواس. يجب أن تقدم إجاباتك في شكل منظم، وتستخدم الجداول والعناصر المرقمة عند طلب المقارنات. كما يمكنك إنشاء أسئلة تدريبية مع تفسير الإجابة بناءً على المحتوى المسترجع. "
    "الإجابات يجب أن تكون دقيقة وواضحة ومبنية بالكامل على المراجع الطبية المتوفرة لديك في قاعدة المعرفة المرفقة. إذا لم تجد الإجابة، اذكر ذلك بوضوح."
)

# ---------------------------------
# 2. بناء/تحميل الفهرس
# ---------------------------------

@st.cache_resource
def setup_rag_engine():
    
    if "GEMINI_API_KEY" not in os.environ and not Path(INDEX_STORAGE_DIR).exists():
        st.error("❌ المفتاح السري لـ Gemini مفقود! يرجى إضافته في Secrets أو الكود.")
        return None

    try:
        llm = Gemini(model="gemini-2.5-flash")
    except Exception as e:
        st.error(f"❌ فشل تهيئة نموذج Gemini: {e}")
        return None

    if Path(INDEX_STORAGE_DIR).exists():
        st.info("🔄 جاري تحميل قاعدة المعرفة الموجودة مسبقًا...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_STORAGE_DIR)
        index = load_index_from_storage(storage_context, llm=llm)
        
    else:
        st.warning("⏳ جاري بناء قاعدة المعرفة لأول مرة (قد يستغرق بضع دقائق)...")
        
        try:
            pdf_documents = SimpleDirectoryReader(input_dir=PDF_DIR, required_exts=[".pdf"]).load_data()
            url_documents = SimpleWebPageReader(input_urls=MEDICAL_URLS).load_data()
            documents = pdf_documents + url_documents
            st.info(f"تم تحميل {len(documents)} مستند. جاري الفهرسة...")

            index = VectorStoreIndex.from_documents(documents, llm=llm)
            index.storage_context.persist(persist_dir=INDEX_STORAGE_DIR)
            st.success("✅ تم بناء قاعدة المعرفة وحفظها بنجاح!")
            
        except Exception as e:
            st.error(f"❌ خطأ حرج في بناء الفهرس: {e}")
            return None

    query_engine = index.as_query_engine(
        llm=llm,
        system_prompt=SYSTEM_PROMPT,
        streaming=True
    )
    return query_engine

# ---------------------------------
# 3. دوال توليد الوسائط (الصور/الجرافيك/الصور المتحركة)
# ---------------------------------

@st.cache_resource
def get_gemini_client():
    return genai.Client()

def generate_image(prompt: str, is_animation=False):
    """
    تستخدم نموذج Imagen لإنشاء صورة ثابتة أو متحركة بناءً على الوصف.
    """
    client = get_gemini_client()
    
    # تحسين المطالبة لإنشاء صورة طبية احترافية
    full_prompt = (
        f"Detailed medical diagram, high-quality colorful graphic design, "
        f"featuring arrows and explanatory labels showing the {prompt}"
    ) # <--- تم تطبيق تحسين "الأسهم والشروحات" هنا!
    
    st.info(f"🎨 جاري توليد {'صورة متحركة (GIF)' if is_animation else 'صورة توضيحية'} لـ: {prompt}")

    try:
        if is_animation:
            st.warning("توليد الفيديو/الصور المتحركة معقد في Streamlit. سيتم توليد صورة ثابتة بدلاً من ذلك.")
            is_animation = False

        if not is_animation:
            result = client.models.generate_images(
                model=IMAGE_GENERATION_MODEL,
                prompt=full_prompt,
                config=dict(
                    number_of_images=1,
                    output_mime_type="image/jpeg",
                    aspect_ratio="16:9"
                )
            )
        
        if result.generated_images:
            image_data = result.generated_images[0].image.image_bytes
            return image_data, None
        else:
            return None, "لم يتمكن النموذج من توليد صورة بناءً على الوصف."

    except Exception as e:
        if "API_KEY_INVALID" in str(e):
            return None, "خطأ: مفتاح Gemini API غير صالح أو غير مهيأ لخدمة Imagen."
        return None, f"خطأ في توليد الصورة: {e}"


# ---------------------------------
# 4. واجهة Streamlit (التطبيق الرئيسي)
# ---------------------------------

st.set_page_config(page_title="مساعدك الطبي الخاص (RAG+Vision)", layout="centered")
st.title("👨‍⚕️ مساعدك الطبي الخاص (Rائد)")
st.caption("يعتمد على مراجعك الطبية وخدمة توليد الصور (Imagen)")

query_engine = setup_rag_engine()

def handle_image_generation(content, is_animation=False):
    # نستخدم جزء من الإجابة لتوليد مطالبة للصورة
    image_prompt = content[:200]
    
    if is_animation:
        image_bytes, error = generate_image(image_prompt, is_animation=True)
    else:
        image_bytes, error = generate_image(image_prompt, is_animation=False)

    if image_bytes:
        st.image(image_bytes, caption=f"صورة توضيحية تم توليدها لـ: {image_prompt}...")
    else:
        st.error(f"فشل التوليد: {error}")


if query_engine:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # إضافة أزرار التوليد بعد كل رد من المساعد (لتحقيق الاسترجاع البصري)
            if message["role"] == "assistant":
                col1, col2 = st.columns(2)
                
                # الزر 1: توليد صورة توضيحية (Graphic Design)
                with col1:
                    if st.button("🖼️ توليد جرافيك توضيحي", key=f"img_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=False)

                # الزر 2: توليد صورة متحركة (كبديل للفيديو)
                with col2:
                    if st.button("🎬 توليد صورة متحركة/فيديو", key=f"gif_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=True)


    if prompt := st.chat_input("اطرح سؤالاً طبياً..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            response = query_engine.query(prompt)
            st.write_stream(response.response_gen)
            st.session_state.messages.append({"role": "assistant", "content": response.response})
    "الإجابات يجب أن تكون دقيقة وواضحة ومبنية بالكامل على المراجع الطبية المتوفرة لديك في قاعدة المعرفة المرفقة. إذا لم تجد الإجابة، اذكر ذلك بوضوح."
# ---------------------------------
# 2. بناء/تحميل الفهرس
# ---------------------------------

@st.cache_resource
def setup_rag_engine():
    
    if "GEMINI_API_KEY" not in os.environ and not Path(INDEX_STORAGE_DIR).exists():
        st.error("❌ المفتاح السري لـ Gemini مفقود! يرجى إضافته في Secrets أو الكود.")
        return None

    try:
        # تهيئة العميل المشترك لـ Gemini (للنموذج اللغوي)
        llm = Gemini(model="gemini-2.5-flash")
    except Exception as e:
        st.error(f"❌ فشل تهيئة نموذج Gemini: {e}")
        return None

    # تحميل الفهرس إذا كان موجوداً
    if Path(INDEX_STORAGE_DIR).exists():
        st.info("🔄 جاري تحميل قاعدة المعرفة الموجودة مسبقًا...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_STORAGE_DIR)
        index = load_index_from_storage(storage_context, llm=llm)
        
    # بناء الفهرس إذا لم يكن موجوداً
    else:
        st.warning("⏳ جاري بناء قاعدة المعرفة لأول مرة (قد يستغرق بضع دقائق)...")
        
        try:
            pdf_documents = SimpleDirectoryReader(input_dir=PDF_DIR, required_exts=[".pdf"]).load_data()
            url_documents = SimpleWebPageReader(input_urls=MEDICAL_URLS).load_data()
            documents = pdf_documents + url_documents
            st.info(f"تم تحميل {len(documents)} مستند. جاري الفهرسة...")

            index = VectorStoreIndex.from_documents(documents, llm=llm)
            index.storage_context.persist(persist_dir=INDEX_STORAGE_DIR)
            st.success("✅ تم بناء قاعدة المعرفة وحفظها بنجاح!")
            
        except Exception as e:
            st.error(f"❌ خطأ حرج في بناء الفهرس: {e}")
            return None

    # إنشاء محرك الاستعلام
    query_engine = index.as_query_engine(
        llm=llm,
        system_prompt=SYSTEM_PROMPT,
        streaming=True
    )
    return query_engine

# ---------------------------------
# 3. دوال توليد الوسائط (الصور/الجرافيك/الصور المتحركة)
# ---------------------------------

# تهيئة عميل Gemini لمهام توليد الصور
@st.cache_resource
def get_gemini_client():
    return genai.Client()

def generate_image(prompt: str, is_animation=False):
    """
    تستخدم نموذج Imagen لإنشاء صورة ثابتة أو متحركة بناءً على الوصف.
    """
    client = get_gemini_client()
    
    # تحسين المطالبة لإنشاء صورة طبية احترافية
    full_prompt = f"Medical illustration, accurate, detailed, and colorful graphic design of: {prompt}"
    
    st.info(f"🎨 جاري توليد {'صورة متحركة (GIF)' if is_animation else 'صورة توضيحية'} لـ: {prompt}")

    try:
        # إذا كانت صورة متحركة (GIF)، نستخدم ميزة الإخراج كفيديو/GIF
        if is_animation:
            result = client.models.generate_images(
                model=IMAGE_GENERATION_MODEL,
                prompt=full_prompt,
                config=dict(
                    number_of_images=1,
                    output_mime_type="video/mp4", # يُفضل فيديو قصير
                    aspect_ratio="1:1"
                )
            )
            # بما أن Streamlit لا يعرض الفيديو/GIF المشفر مباشرة من بايتس Gemini،
            # نحتاج إلى طريقة مختلفة للعرض (قد تتطلب حفظ الملف في Replit أولاً، لكننا سنتجاوزها حالياً بعرض الصورة الثابتة الأسهل).
            # سنكتفي هنا بعرض الصورة الثابتة كبديل مضمون.
            st.warning("توليد الفيديو/الصور المتحركة معقد في Streamlit. سيتم توليد صورة ثابتة بدلاً من ذلك.")
            is_animation = False

        # توليد صورة ثابتة
        if not is_animation:
            result = client.models.generate_images(
                model=IMAGE_GENERATION_MODEL,
                prompt=full_prompt,
                config=dict(
                    number_of_images=1,
                    output_mime_type="image/jpeg",
                    aspect_ratio="16:9"
                )
            )
        
        if result.generated_images:
            image_data = result.generated_images[0].image.image_bytes
            return image_data, None
        else:
            return None, "لم يتمكن النموذج من توليد صورة بناءً على الوصف."

    except Exception as e:
        # تحقق مما إذا كان السبب هو عدم إعداد مفتاح API
        if "API_KEY_INVALID" in str(e):
            return None, "خطأ: مفتاح Gemini API غير صالح أو غير مهيأ لخدمة Imagen."
        return None, f"خطأ في توليد الصورة: {e}"


# ---------------------------------
# 4. واجهة Streamlit (التطبيق الرئيسي)
# ---------------------------------

st.set_page_config(page_title="مساعدك الطبي الخاص (RAG+Vision)", layout="centered")
st.title("👨‍⚕️ مساعدك الطبي الخاص (Rائد)")
st.caption("يعتمد على مراجعك الطبية وخدمة توليد الصور (Imagen)")

query_engine = setup_rag_engine()

# وظيفة مخصصة للاستجابة عند الضغط على زر توليد الصورة
def handle_image_generation(content, is_animation=False):
    # نستخدم جزء من الإجابة لتوليد مطالبة للصورة
    image_prompt = content[:200]
    
    # تحديد نوع التوليد
    if is_animation:
        image_bytes, error = generate_image(image_prompt, is_animation=True)
    else:
        image_bytes, error = generate_image(image_prompt, is_animation=False)

    if image_bytes:
        st.image(image_bytes, caption=f"صورة توضيحية تم توليدها لـ: {image_prompt}...")
    else:
        st.error(f"فشل التوليد: {error}")


if query_engine:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # إضافة أزرار التوليد بعد كل رد من المساعد (لتحقيق الاسترجاع البصري)
            if message["role"] == "assistant":
                col1, col2 = st.columns(2)
                
                # الزر 1: توليد صورة توضيحية (Graphic Design)
                with col1:
                    if st.button("🖼️ توليد جرافيك توضيحي", key=f"img_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=False)

                # الزر 2: توليد صورة متحركة (كبديل للفيديو)
                with col2:
                    if st.button("🎬 توليد صورة متحركة/فيديو", key=f"gif_{hash(message['content'])}"):
                        handle_image_generation(message['content'], is_animation=True)


# هذا جزء من الكود الذي يمكنك تعديله (في دالة handle_image_generation)

# تحسين المطالبة لتوليد صورة ذات أسهم وشروحات
full_prompt = (
    f"Detailed medical diagram, high-quality colorful graphic design, "
    f"featuring arrows and explanatory labels showing the {image_prompt}"
)

    
if prompt := st.chat_input("اطرح سؤالاً طبياً..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            response = query_engine.query(prompt)
            st.write_stream(response.response_gen)
            st.session_state.messages.append({"role": "assistant", "content": response.response})
    
# **مهم:** الـ SYSTEM PROMPT المحدث بناءً على طلبك
SYSTEM_PROMPT = (
    "أنت مساعد طبي ذكي متخصص في الإجابة على استفسارات طلاب الطب. "
    "يجب أن تكون إجاباتك دقيقة وواضحة ومبنية بالكامل على المراجع الطبية "
    "المتوفرة لديك في قاعدة المعرفة المرفقة. إذا لم تجد الإجابة، اذكر ذلك بوضوح. "
    "الإجابة يجب أن تكون باللغة العربية، مع الحفاظ على **المصطلحات الطبية الأساسية (الأمراض، الأدوية، المصطلحات التشريحية)** باللغة الإنجليزية/اللاتينية داخل الأقواس. يجب أن تقدم إجاباتك في شكل منظم، وتستخدم الجداول والعناصر المرقمة عند طلب المقارنات. كما يمكنك إنشاء أسئلة تدريبية مع تفسير الإجابة بناءً على المحتوى المسترجع."
)


# ---------------------------------
# 2. بناء/تحميل الفهرس (@st.cache_resource)
# ---------------------------------

@st.cache_resource
def setup_rag_engine():
    
    # التحقق من مفتاح API
    if "GEMINI_API_KEY" not in os.environ and not Path(INDEX_STORAGE_DIR).exists():
        st.error("❌ المفتاح السري لـ Gemini مفقود! يرجى إضافته في Secrets أو الكود.")
        return None

    llm = Gemini(model="gemini-2.5-flash")

    # تحميل الفهرس إذا كان موجوداً
    if Path(INDEX_STORAGE_DIR).exists():
        st.info("🔄 جاري تحميل قاعدة المعرفة الموجودة مسبقًا...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_STORAGE_DIR)
        index = load_index_from_storage(storage_context, llm=llm)
        
    # بناء الفهرس إذا لم يكن موجوداً
    else:
        st.warning("⏳ جاري بناء قاعدة المعرفة لأول مرة (قد يستغرق بضع دقائق)...")
        
        try:
            # قراءة ملفات PDF
            pdf_documents = SimpleDirectoryReader(input_dir=PDF_DIR, required_exts=[".pdf"]).load_data()
            # قراءة المواقع الإلكترونية
            url_documents = SimpleWebPageReader(input_urls=MEDICAL_URLS).load_data()
            documents = pdf_documents + url_documents
            st.info(f"تم تحميل {len(documents)} مستند. جاري الفهرسة...")

            # بناء الفهرس وحفظه
            index = VectorStoreIndex.from_documents(
                documents,
                llm=llm,
            )
            index.storage_context.persist(persist_dir=INDEX_STORAGE_DIR)
            st.success("✅ تم بناء قاعدة المعرفة وحفظها بنجاح! البرنامج جاهز.")
            
        except Exception as e:
            st.error(f"❌ خطأ حرج في بناء الفهرس: {e}")
            return None

    # إنشاء محرك الاستعلام
    query_engine = index.as_query_engine(
        llm=llm,
        system_prompt=SYSTEM_PROMPT,
        streaming=True
    )
    return query_engine

# ---------------------------------
# 3. واجهة Streamlit (التطبيق الرئيسي)
# ---------------------------------

st.set_page_config(page_title="مساعدك الطبي الخاص (RAG)", layout="centered")
st.title("👨‍⚕️ مساعدك الطبي الخاص")
st.caption("يعتمد على مراجعك الطبية (PDFs + URLs) باستخدام Gemini 2.5 Flash")

query_engine = setup_rag_engine()

if query_engine:
    # تهيئة سجل الدردشة
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # عرض الرسائل السابقة
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # مربع إدخال المستخدم
    if prompt := st.chat_input("اطرح سؤالاً طبياً..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # استدعاء محرك الاستعلام وتوليد الرد
        with st.chat_message("assistant"):
            response = query_engine.query(prompt)
            st.write_stream(response.response_gen)
            # تخزين الرد الكامل في الجلسة
            st.session_state.messages.append({"role": "assistant", "content": response.response})
            "https://www.medscape.com/",
    
    # Johns Hopkins Medicine (طب جونز هوبكنز)
    "https://www.hopkinsmedicine.org/",
    
    # ملاحظة: يمكنك إضافة أي رابط آخر تريد أن يستقي منه النموذج معلوماته هنا
    # "https://your-favorite-university-medical-journal.com/article", 

SYSTEM_PROMPT = (
    "أنت مساعد طبي ذكي متخصص في الإجابة على استفسارات طلاب الطب. "
    "يجب أن تكون إجاباتك دقيقة وواضحة ومبنية بالكامل على المراجع الطبية "
    "المتوفرة لديك في قاعدة المعرفة المرفقة. إذا لم تجد الإجابة، اذكر ذلك بوضوح. "
    "الردود يجب أن تكون باللغة العربية مع ذكر المصطلحات الطبية بالإنجليزية/اللاتينية حيثما لزم الأمر."
      "الإجابة يجب أن تكون باللغة العربية المصريه أو العامية المصرية أو  الانجليزيه ، مع الحفاظ على **المصطلحات الطبية الأساسية (الأمراض، الأدوية، المصطلحات التشريحية)** باللغة الإنجليزية/اللاتينية داخل الأقواس. يجب أن تقدم إجاباتك في شكل منظم، وتستخدم الجداول والعناصر المرقمة عند طلب المقارنات."
)

# ---------------------------------
# 2. بناء/تحميل الفهرس
# ---------------------------------

@st.cache_resource
def setup_rag_engine():
    
    # التحقق من وجود المفتاح قبل البدء
    if "GEMINI_API_KEY" not in os.environ and not Path(INDEX_STORAGE_DIR).exists():
        st.error("❌ المفتاح السري لـ Gemini مفقود! يرجى إضافته في Secrets أو الكود.")
        return None

    llm = Gemini(model="gemini-2.5-flash")

    if Path(INDEX_STORAGE_DIR).exists():
        st.info("🔄 جاري تحميل قاعدة المعرفة الموجودة مسبقًا...")
        storage_context = StorageContext.from_defaults(persist_dir=INDEX_STORAGE_DIR)
        index = load_index_from_storage(storage_context, llm=llm)
        
    else:
        st.warning("⏳ جاري بناء قاعدة المعرفة لأول مرة (سيعتمد على قوة اتصالك بالإنترنت)...")
        
        try:
            pdf_documents = SimpleDirectoryReader(input_dir=PDF_DIR, required_exts=[".pdf"]).load_data()
            url_documents = SimpleWebPageReader(input_urls=MEDICAL_URLS).load_data()
            documents = pdf_documents + url_documents
            st.info(f"تم تحميل {len(documents)} مستند. جاري الفهرسة...")

            index = VectorStoreIndex.from_documents(
                documents,
                llm=llm,
            )
            index.storage_context.persist(persist_dir=INDEX_STORAGE_DIR)
            st.success("✅ تم بناء قاعدة المعرفة وحفظها بنجاح! البرنامج جاهز.")
            
        except Exception as e:
            st.error(f"❌ خطأ حرج في بناء الفهرس: {e}")
            return None

    # إنشاء محرك الاستعلام
    query_engine = index.as_query_engine(
        llm=llm,
        system_prompt=SYSTEM_PROMPT,
        streaming=True
    )
    return query_engine

# ---------------------------------
# 3. واجهة Streamlit (التطبيق)
# ---------------------------------

st.set_page_config(page_title="مساعدك الطبي الخاص (RAG)", layout="centered")
st.title("👨‍⚕️ مساعدك الطبي الخاص")
st.caption("يعتمد على مراجعك الطبية (PDFs + URLs) باستخدام Gemini 2.5 Flash")

query_engine = setup_rag_engine()

if query_engine:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("اطرح سؤالاً طبياً..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            response = query_engine.query(prompt)
            st.write_stream(response.response_gen)
            st.session_state.messages.append({"role": "assistant", "content": response.response})     