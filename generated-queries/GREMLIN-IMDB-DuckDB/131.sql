SELECT count(*)
FROM aka_title, company_type, complete_cast, info_type, kind_type, movie_companies, movie_info, movie_link, name, person_info, title
WHERE info_type.info = 'genres'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
