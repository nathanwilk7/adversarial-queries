SELECT count(*)
FROM aka_title, cast_info, company_name, kind_type, movie_companies, name, role_type, title
WHERE kind_type.kind = 'movie'
  AND name.name_pcode_nf = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND title.kind_id = kind_type.id;
