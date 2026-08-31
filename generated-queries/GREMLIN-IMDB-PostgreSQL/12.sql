SELECT count(*)
FROM aka_name, company_name, complete_cast, info_type, movie_companies, movie_info, name, person_info, title
WHERE company_name.name_pcode_sf = ''
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
