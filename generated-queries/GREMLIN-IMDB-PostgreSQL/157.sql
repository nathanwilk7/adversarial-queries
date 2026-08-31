SELECT count(*)
FROM aka_title, company_name, info_type, kind_type, movie_companies, movie_info, name, person_info, title
WHERE company_name.name_pcode_sf = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
